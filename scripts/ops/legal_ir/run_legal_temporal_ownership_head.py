#!/usr/bin/env python3
"""Matched source-only/occurrence-aware temporal owner-TYPE pilot.

Fresh reference files are never opened here. Training and tuning references
score saved source-only generations. Selection precedes all fresh generation.
The independent qualifier owns fresh scoring after generation freezes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import sys

os.environ['CUDA_VISIBLE_DEVICES']='-1'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_ownership_head as runtime

SCHEMA='legal-temporal-owner-type-experiment/v1'
CONFIG_SCHEMA='legal-temporal-owner-type-config/v1'
PARENT_SHA='4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea'
SEEDS=(1730,1731)
STAGES=(50,100,200)
SEALED_KEYS=('fresh_targets','multi_fresh_targets','fresh_annotation_ledger','exposure_audit')
_GUARD_STATE={'paths':set(),'attempts':[],'installed':False}
require=runtime.require
digest=runtime.digest


def reference(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def read(pin):
    actual=reference(pin['path'])
    require(all(actual[k]==pin[k] for k in ('sha256','bytes') if k in pin),'file binding changed: '+pin['path'])
    return json.loads(Path(pin['path']).read_bytes())


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as handle:json.dump(value,handle,sort_keys=True,indent=2,allow_nan=False);handle.write('\n')
    return reference(path)


def install_fresh_reference_guard(config_path):
    """Install before corpus loading, independently in each spawned worker."""
    config=read(reference(config_path));manifest=read(config['corpus_manifest'])
    paths={str(Path(manifest['artifacts'][key]['path']).resolve()) for key in SEALED_KEYS}
    require(len(paths)==4,'four distinct fresh semantic/evidence seals required')
    _GUARD_STATE['paths'].update(paths)
    if not _GUARD_STATE['installed']:
        def audit(event,args):
            if event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
            path=str(Path(os.fsdecode(args[0])).resolve())
            if path in _GUARD_STATE['paths']:
                _GUARD_STATE['attempts'].append(path)
                raise PermissionError('fresh reference sealed through generation freeze: '+path)
        sys.addaudithook(audit);_GUARD_STATE['installed']=True
    return {'sealed_paths':sorted(paths),'premature_read_attempts':len(_GUARD_STATE['attempts'])}


def producer_pins():
    from scripts.ops.legal_ir import prepare_legal_temporal_ownership_corpus as corpus
    result=runtime.producer_pins()
    for module in (corpus,):result[str(Path(module.__file__).resolve())]=reference(module.__file__)['sha256']
    result[str(Path(__file__).resolve())]=reference(__file__)['sha256']
    # Include the producer's schema/renderer helper when exposed by its module.
    for value in vars(corpus).values():
        filename=getattr(value,'__file__',None)
        if filename and Path(filename).name=='legal_temporal_ownership_corpus.py':
            result[str(Path(filename).resolve())]=reference(filename)['sha256']
    return result


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_temporal_ownership_corpus as corpus
    pin=reference(path);config=read(pin)
    require(set(config)=={'schema','corpus_manifest','parent','study_design','producer_files'} and config['schema']==CONFIG_SCHEMA,
            'closed ownership experiment config required')
    require(config['parent']['sha256']==PARENT_SHA,'exact original grounding temporal400 parent required')
    parent=read(config['parent']);read(config['study_design']);manifest=read(config['corpus_manifest'])
    for value in config['producer_files']:require(reference(value['path'])==value,'producer file changed')
    pinned={v['path']:v['sha256'] for v in config['producer_files']}
    require(all(pinned.get(k)==v for k,v in producer_pins().items()),'complete producer dependency pins required')
    data=corpus.load_training_inputs(config['corpus_manifest']['path'])
    training=runtime.project_training_rows(data['train']);tuning=runtime.project_training_rows(data['tuning'])
    runtime._splits(training,tuning)
    require(len(training)==768 and len(tuning)==144 and len(data['fresh_sources'])==192 and len(data['multi_fresh_sources'])==96,
            'prospective corpus count differs')
    return {'config':config,'config_ref':pin,'manifest':manifest,'parent':parent,'training':training,'tuning':tuning,
            'fresh_sources':data['fresh_sources'],'multi_fresh_sources':data['multi_fresh_sources']}


def metrics(rows,targets):
    wanted={row['id']:row for row in targets}
    require(len(rows)==len(targets)==len(wanted) and {r['id'] for r in rows}==set(wanted),'complete unique scoring inventory required')
    confusion=[[0]*4 for _ in range(4)];nll=brier=0.;bins=[[] for _ in range(10)]
    accepted=accepted_wrong=ambiguous_confident_errors=0
    for row in rows:
        target=wanted[row['id']]
        require(row['source_sha256']==target['source_sha256'] and row['proposed_time_span']==target['proposed_time_span'],
                'prediction occurrence differs from target')
        probs=row['probabilities'];logits=row['logits']
        require(len(probs)==len(logits)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in probs+logits),'finite four-class outputs required')
        require(all(0<=p<=1 for p in probs) and abs(sum(probs)-1)<1e-6,'invalid probability vector')
        gold=runtime.CLASSES.index(target['label']);pred=max(range(4),key=lambda i:probs[i])
        require(row['predicted_label']==runtime.CLASSES[pred] and row['confidence']==probs[pred],'prediction class/confidence mismatch')
        expected_accept=pred!=3 and probs[pred]>=.8
        require((row['status']=='accepted')==expected_accept and row['owner_type']==(runtime.CLASSES[pred] if expected_accept else None),
                'fixed decision policy differs')
        confusion[gold][pred]+=1
        maximum=max(logits);nll+=maximum+math.log(sum(math.exp(x-maximum) for x in logits))-logits[gold]
        brier+=sum((p-(i==gold))**2 for i,p in enumerate(probs))
        bins[min(9,int(probs[pred]*10))].append((probs[pred],pred==gold))
        if expected_accept:
            accepted+=1;accepted_wrong+=pred!=gold;ambiguous_confident_errors+=gold==3
    classes={};f1=[]
    for index,label in enumerate(runtime.CLASSES):
        support=sum(confusion[index]);tp=confusion[index][index];fp=sum(r[index] for r in confusion)-tp;fn=support-tp
        value=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.;f1.append(value)
        classes[label]={'support':support,'correct':tp,'false_positive':fp,'false_negative':fn,'f1':value}
    n=len(rows)
    return {'count':n,'class_order':list(runtime.CLASSES),'confusion':confusion,'per_class':classes,
            'correct':sum(confusion[i][i] for i in range(4)),'accuracy':sum(confusion[i][i] for i in range(4))/n,
            'macro_f1':sum(f1)/4,'nll':nll/n,'brier':brier/n,
            'ece_10':sum(len(b)/n*abs(sum(p for p,_ in b)/len(b)-sum(y for _,y in b)/len(b)) for b in bins if b),
            'calibration_bins':[{'count':len(b),'confidence_sum':sum(p for p,_ in b),'correct':sum(y for _,y in b)} for b in bins],
            'accepted':accepted,'deferred':n-accepted,'coverage':accepted/n,'accepted_wrong':accepted_wrong,
            'selective_risk':accepted_wrong/accepted if accepted else None,
            'ambiguous_support':classes['ambiguous']['support'],'ambiguous_confident_errors':ambiguous_confident_errors,
            'references_used_for_scoring_only':True,'owner_occurrence_resolved':False}


def stage_rank(stage):
    value=stage['tuning_metrics'];return (-value['macro_f1'],value['nll'],stage['steps'])


def select_stage(stages):
    require(tuple(s['steps'] for s in stages)==STAGES,'all prospective stages required')
    return min(stages,key=stage_rank)


def generate(checkpoint_pin,sources_pin,output):
    checkpoint=runtime.load_checkpoint(checkpoint_pin['path'],expected_sha256=checkpoint_pin['sha256'])
    sources=read(sources_pin);model=runtime.TemporalOwnershipHead(checkpoint);rows=[]
    for begin in range(0,len(sources),48):rows.extend(model.predict_many(sources[begin:begin+48]))
    value={'schema':'legal-temporal-owner-type-source-generation/v1','model':{'checkpoint':checkpoint_pin,
        'arm':checkpoint['config']['arm'],'seed':checkpoint['config']['seed'],'steps':checkpoint['optimizer_steps']},
        'sources':sources_pin,'class_order':list(runtime.CLASSES),'threshold':.8,'rows':rows,
        'encoder_batch_forwards':model.encoder_batch_forwards,'encoder_source_evaluations':model.encoder_source_evaluations,
        'labels_supplied':False,'source_text_conditioned':True,'time_occurrence_conditioned':checkpoint['config']['arm']!='source_only',
        'source_id_used_as_feature':False,'owner_or_cue_spans_supplied':False,**runtime.FALSE}
    return write(output,value),value


def prepare_initials(config_path,output):
    guard=install_fresh_reference_guard(config_path)
    inputs=load_config(config_path);output=Path(output);require(not output.exists(),'fresh initialization directory required')
    output.mkdir(parents=True);models={};states={};heads={}
    for seed in SEEDS:
        for arm in runtime.ARMS:
            name=f'{arm}-{seed}'
            checkpoint=runtime.build_checkpoint(inputs['parent'],inputs['training'],inputs['tuning'],arm=arm,seed=seed,
                                                 parent_file_sha256=inputs['config']['parent']['sha256'])
            pin=runtime.save_checkpoint(checkpoint,output/f'{name}.json');models[name]=pin
            states[name]=checkpoint['initial_state_sha256'];heads[name]=digest({k:v for k,v in checkpoint['model_state'].items() if k.startswith('head.')})
        require(len({states[f'{arm}-{seed}'] for arm in runtime.ARMS})==1,'paired arm initialization differs')
    result=write(output/'initialization-frozen.json',{'schema':SCHEMA,'config':inputs['config_ref'],'models':models,
        'initial_state_digests':states,'head_digests':heads,'source_encoder_parent':inputs['config']['parent'],
        'training_manifest_sha256':digest(inputs['training']),'tuning_manifest_sha256':digest(inputs['tuning']),
        'optimizer_steps':0,'fresh_references_opened':False,'fresh_reference_guard':guard,'producer_pins':producer_pins()})
    print(json.dumps({'phase':'initialization_frozen','reference':result}),flush=True);return result


def fit_trial(config_path,initial_freeze_pin,sources,output,name):
    guard=install_fresh_reference_guard(config_path)
    inputs=load_config(config_path);initials=read(initial_freeze_pin);require(initials['config']==inputs['config_ref'],'initial configuration differs')
    output=Path(output)/name;output.mkdir(parents=True,exist_ok=False)
    initial=initials['models'][name];checkpoint=runtime.load_checkpoint(initial['path'],expected_sha256=initial['sha256'])
    initial_evaluation={}
    for panel in ('training','tuning'):
        pin,value=generate(initial,sources[panel],output/f'initial-{panel}.json')
        initial_evaluation[panel]={'generation':pin,'metrics':metrics(value['rows'],inputs[panel])}
    stages=[]
    for step in STAGES:
        checkpoint,report=runtime.train(checkpoint,inputs['training'],inputs['tuning'],additional_steps=step-checkpoint['optimizer_steps'],max_seconds=600)
        cp_pin=runtime.save_checkpoint(checkpoint,output/f'checkpoint-{step}.json')
        report_pin=write(output/f'training-{step}.json',report)
        stage={'steps':step,'checkpoint':cp_pin,'training_report':report_pin}
        for panel in ('training','tuning'):
            pin,value=generate(cp_pin,sources[panel],output/f'stage-{step}-{panel}.json')
            stage[panel+'_generation']=pin;stage[panel+'_metrics']=metrics(value['rows'],inputs[panel])
        stages.append(stage)
        print(json.dumps({'phase':'stage','trial':name,'steps':step,'train_exact':stage['training_metrics']['correct'],
                          'tune_exact':stage['tuning_metrics']['correct'],'tune_f1':stage['tuning_metrics']['macro_f1']}),flush=True)
    selected=select_stage(stages)
    return write(output/'trial.json',{'schema':SCHEMA,'name':name,'arm':checkpoint['config']['arm'],'seed':checkpoint['config']['seed'],
        'initial_checkpoint':initial,'initial_evaluation':initial_evaluation,'stages':stages,'selected_steps':selected['steps'],
        'selected_checkpoint':selected['checkpoint'],'selection':'tuning_macro_f1_then_nll_then_earlier',
        'fresh_references_opened':False,'fresh_reference_guard':{**guard,'premature_read_attempts':len(_GUARD_STATE['attempts'])},
        'selected_is_pipeline_promotion':False})


def run(config_path,initials_path,output,*,workers=2):
    require(type(workers) is int and 1<=workers<=2,'at most two one-thread workers required')
    guard=install_fresh_reference_guard(config_path)
    inputs=load_config(config_path);output=Path(output);require(not output.exists(),'fresh run directory required')
    initials_pin=reference(initials_path);initials=read(initials_pin)
    require(initials['config']==inputs['config_ref'] and initials['producer_pins']==producer_pins(),'initial freeze differs')
    output.mkdir(parents=True)
    sources={panel:write(output/f'{panel}-sources.json',runtime.source_queries(inputs[panel]) if panel in ('training','tuning') else inputs[panel])
             for panel in ('training','tuning','fresh_sources','multi_fresh_sources')}
    jobs=[f'{arm}-{seed}' for seed in SEEDS for arm in runtime.ARMS];trials=[]
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        futures={pool.submit(fit_trial,config_path,initials_pin,sources,output,name):name for name in jobs}
        for future in as_completed(futures):trials.append(future.result())
    trial_values=sorted([read(pin) for pin in trials],key=lambda t:t['name'])
    training_counters=Counter();exposures={};schedules={}
    for trial in trial_values:
        traces=[]
        for stage in trial['stages']:
            report=read(stage['training_report']);traces.extend(report['trace'])
            training_counters.update({key:report[key] for key in ('steps_executed','encoder_batch_forwards','encoder_source_evaluations')})
        require([r['step'] for r in traces]==list(range(1,201)),'complete ordered 200-update trial required')
        counts=Counter(identity for row in traces for identity in row['query_ids'])
        groups=Counter(identity for row in traces for identity in row['group_ids'])
        exposures[trial['name']]={'query_draws':sum(counts.values()),'distinct_queries':len(counts),
            'group_draws':sum(groups.values()),'distinct_groups':len(groups),'query_counts':dict(counts),'group_counts':dict(groups)}
        schedules[trial['name']]=digest([{'query_ids':r['query_ids'],'group_ids':r['group_ids']} for r in traces])
    for seed in SEEDS:
        require(len({schedules[f'{arm}-{seed}'] for arm in runtime.ARMS})==1,'matched-arm batch schedules differ')
    require(training_counters=={'steps_executed':1200,'encoder_batch_forwards':1200,'encoder_source_evaluations':19200},'training totals differ')
    selections=write(output/'selections-frozen.json',{'schema':SCHEMA,'config':inputs['config_ref'],'initialization_freeze':initials_pin,
        'trials':trial_values,'trial_references':sorted(trials,key=lambda p:p['path']), 'fresh_references_opened':False,
        'training_exposures':exposures,'training_schedule_sha256':schedules,
        'total_optimizer_updates':training_counters['steps_executed'],'no_pipeline_promotion':True})
    cache={};logical=[];actual=[]
    for trial in trial_values:
        for role,cp_pin in (('selected',trial['selected_checkpoint']),('final200',trial['stages'][-1]['checkpoint'])):
            for panel in ('fresh_sources','multi_fresh_sources'):
                key=digest({'checkpoint':cp_pin['sha256'],'sources':sources[panel]['sha256']})
                executed=key not in cache
                if executed:
                    pin,value=generate(cp_pin,sources[panel],output/'generations'/f'{key}.json');cache[key]=pin
                    actual.append({'key':key,'generation':pin,'encoder_batch_forwards':value['encoder_batch_forwards'],
                                   'encoder_source_evaluations':value['encoder_source_evaluations']})
                logical.append({'slot':trial['name']+'__'+role,'arm':trial['arm'],'seed':trial['seed'],'role':role,'panel':panel,
                                'checkpoint':cp_pin,'generation':cache[key],'generation_key':key,'executed_here':executed})
    all_eval=[]
    for trial in trial_values:
        all_eval.extend(v['generation'] for v in trial['initial_evaluation'].values())
        all_eval.extend(stage[panel+'_generation'] for stage in trial['stages'] for panel in ('training','tuning'))
    admitted_counters=Counter()
    for pin in all_eval:
        value=read(pin);admitted_counters.update({k:value[k] for k in ('encoder_batch_forwards','encoder_source_evaluations')})
    result=write(output/'generation-frozen.json',{'schema':SCHEMA,'config':inputs['config_ref'],'initialization_freeze':initials_pin,
        'selections':selections,'sources':sources,'logical_generations':logical,'executed_generations':actual,
        'logical_generation_slots':len(logical),'physical_generation_files':len(actual),
        'logical_fresh_query_rows':sum(len(inputs[r['panel']]) for r in logical),
        'physical_fresh_query_rows':sum(r['encoder_source_evaluations'] for r in actual),
        'physical_fresh_encoder_batch_forwards':sum(r['encoder_batch_forwards'] for r in actual),
        'admitted_generation_counters':dict(admitted_counters),'training_encoder_batch_forwards':training_counters['encoder_batch_forwards'],
        'training_encoder_source_evaluations':training_counters['encoder_source_evaluations'],'total_optimizer_updates':training_counters['steps_executed'],
        'all_training_selection_and_generation_complete':True,'fresh_references_opened':False,
        'fresh_reference_guard':{**guard,'premature_read_attempts':len(_GUARD_STATE['attempts'])},
        'producer_pins':producer_pins(),'models_are_unqualified_research_heads':True})
    print(json.dumps({'phase':'generation_frozen','reference':result}),flush=True);return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--prepare-initials',action='store_true')
    parser.add_argument('--initials');parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args(argv)
    if args.prepare_initials:return prepare_initials(args.config,args.output)
    require(args.initials is not None,'frozen initialization required before training')
    return run(args.config,args.initials,args.output,workers=args.workers)


if __name__=='__main__':main()
