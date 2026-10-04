#!/usr/bin/env python3
"""Matched-budget relative owner features and norm contrast pilot; no deployment.

Only placement tuning selects a stage. Old panels describe regressions and new
fresh references remain sealed until all selection and generation has finished.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
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
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_relative_owner as runtime
from ipfs_datasets_py.logic.autoformal import legal_temporal_relative_owner_corpus as corpus
from ipfs_datasets_py.logic.autoformal import legal_temporal_relative_owner_metrics as metrics
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as type_metrics

SCHEMA='legal-temporal-relative-owner-study/v1'
CONFIG_SCHEMA='legal-temporal-relative-owner-config/v1'
SEEDS=(1730,1731)
STAGES=(0,100,200)
PANELS=('fresh_lexical','fresh_structural')
CALIBRATION=('calibration_lexical','calibration_structural')
ALL_PANELS=CALIBRATION+PANELS
SEALED=('fresh_lexical_targets','fresh_structural_targets','fresh_annotation_ledger','exposure_audit',
        'calibration_lexical_targets','calibration_structural_targets','calibration_annotation_ledger','calibration_exposure_audit')
PARENTS={1730:'ff238ee5e647c66edd6afc9e0fe4ea213c9e65e3306bc9680445975d0cbcb220',
         1731:'f3729e41592d9a805a98fac190801530f4345bed04c958b5bfdd17a37347fe59'}
GUARD={'paths':set(),'attempts':[],'installed':False}
require=runtime.require


def ref(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def read(pin):
    require(ref(pin['path'])==pin,'referenced bytes changed')
    return json.loads(Path(pin['path']).read_bytes())


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    return ref(path)


def producer_pins():
    result=dict(runtime.producer_pins())
    for module in (corpus,metrics,metrics.previous,metrics.previous.previous,type_metrics):result[str(Path(module.__file__).resolve())]=ref(module.__file__)['sha256']
    for pin in corpus.producers():result[pin['path']]=pin['sha256']
    result[str(Path(__file__).resolve())]=ref(__file__)['sha256']
    return result


def install_guard(config_path):
    cfg=read(ref(config_path));manifest=read(cfg['corpus_manifest'])
    GUARD['paths'].update(str(Path(manifest['artifacts'][k]['path']).resolve()) for k in SEALED)
    require(len(GUARD['paths'])==8,'eight current semantic references required')
    if not GUARD['installed']:
        def hook(event,args):
            if event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
            name=str(Path(os.fsdecode(args[0])).resolve())
            if name in GUARD['paths']:
                GUARD['attempts'].append(name);raise PermissionError('calibration and evaluation references remain sealed')
        sys.addaudithook(hook);GUARD['installed']=True


def guard_receipt():
    return {'sealed_paths':sorted(GUARD['paths']),'premature_read_attempts':list(GUARD['attempts']),'released':False}


def load_config(path):
    pin=ref(path);cfg=read(pin)
    require(set(cfg)=={'schema','corpus_manifest','parents','study_design','producer_files','diagnostic_sources'}
            and cfg['schema']==CONFIG_SCHEMA,'closed pointer configuration required')
    require(set(cfg['parents'])=={str(s) for s in SEEDS},'two declared parents required')
    for seed in SEEDS:
        require(cfg['parents'][str(seed)]['sha256']==PARENTS[seed],'warm parent changed')
        read(cfg['parents'][str(seed)])
    read(cfg['study_design'])
    for file in cfg['producer_files']:require(ref(file['path'])==file,'frozen producer changed')
    pins={p['path']:p['sha256'] for p in cfg['producer_files']}
    require(all(pins.get(p)==sha for p,sha in producer_pins().items()),'incomplete producer closure')
    data=corpus.load_training_inputs(cfg['corpus_manifest']['path'])
    require(len(data['training'])==3360 and len(data['tuning'])==288,'fixed supervised split counts changed')
    require(len(data['retention_targets'])==8,'eight prior diagnostic panels required')
    require(all(len(data[p+'_sources'])==144 for p in ALL_PANELS),'fixed fresh panel counts changed')
    runtime._splits(data['training'],data['tuning'],data['training_other_norm_contrasts'])
    if cfg['diagnostic_sources'] is not None:
        for query in read(cfg['diagnostic_sources']):type_metrics.validate_source(query)
    return cfg,pin,data


def target_map(rows):
    require(len({r['id'] for r in rows})==len(rows),'duplicate supervised query IDs')
    return {r['id']:{'label':r['label'],'owner_anchor_span':r['owner_anchor_span']} for r in rows}


def select(stages):
    require([r['steps'] for r in stages]==list(STAGES),'all three fixed stages required')
    require(all(type(r['tuning_metrics']['joint_correct']) is int and
                0<=r['tuning_metrics']['joint_correct']<=288 and
                type(r['tuning_metrics']['selection_nll']) in (int,float) and
                math.isfinite(r['tuning_metrics']['selection_nll']) and
                r['tuning_metrics']['selection_nll']>=0 for r in stages),'bounded finite tuning rank required')
    return min(stages,key=lambda r:(-r['tuning_metrics']['joint_correct'],r['tuning_metrics']['selection_nll'],r['steps']))


def generate(checkpoint,sources,output,*,kind='relative_owner'):
    require(kind in ('relative_owner','parent_coupled'),'declared decoder kind required')
    if kind=='relative_owner':
        cp=runtime.load_checkpoint(checkpoint['path'],expected_sha256=checkpoint['sha256'])
        decoder=runtime.RelativeTemporalOwnerPointer(cp)
    else:
        cp=runtime.parent.load_checkpoint(checkpoint['path'],expected_sha256=checkpoint['sha256'])
        decoder=runtime.parent.CoupledTemporalOwnerPointer(cp)
    queries=read(sources);predictions=[]
    for start in range(0,len(queries),48):predictions.extend(decoder.predict_many(queries[start:start+48]))
    require(len(predictions)==len(queries),'incomplete model generation')
    payload={'schema':'legal-temporal-relative-owner-generation/v1','checkpoint':checkpoint,'decoder_kind':kind,
             'sources':sources,'rows':predictions,'encoder_batch_forwards':decoder.encoder_batch_forwards,
             'encoder_source_evaluations':decoder.encoder_source_evaluations,
             'source_only_input':True,'reference_anchors_supplied':False,'labels_supplied':False,
             'pipeline_promotion':False,'statutory_semantics_verified':False}
    return write(output,payload),payload


def initialize(config_path,output):
    install_guard(config_path);cfg,pin,data=load_config(config_path)
    output=Path(output);output.mkdir(parents=True,exist_ok=False);models={};initial_states={}
    for seed in SEEDS:
        parent=read(cfg['parents'][str(seed)])
        for arm in runtime.ARMS:
            name=f'{arm}-{seed}'
            cp=runtime.build_checkpoint(parent,data['training'],data['tuning'],training_contrasts=data['training_other_norm_contrasts'],arm=arm,seed=seed,
                parent_file_sha256=cfg['parents'][str(seed)]['sha256'])
            runtime.save_checkpoint(cp,output/(name+'.json'));models[name]=ref(output/(name+'.json'))
            initial_states[name]=cp['initial_state_sha256']
        require(len({initial_states[f'{a}-{seed}'] for a in runtime.ARMS})==1,'arm initial tensors differ')
    return write(output/'initialization-frozen.json',{'schema':SCHEMA,'config':pin,'models':models,
        'parents':cfg['parents'],'initial_state_digests':initial_states,'optimizer_updates':0,
        'fresh_reference_guard':guard_receipt(),'producer_pins':producer_pins()})


def parity(config_path,initial_path,output):
    """Compare all inherited output fields on actual tuning before any fitting."""
    install_guard(config_path);cfg,pin,data=load_config(config_path)
    initial_pin=ref(initial_path);initial=read(initial_pin)
    require(initial['config']==pin and initial['optimizer_updates']==0,'zero-update initialization required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    sources=write(output/'tuning-sources.json',runtime.source_queries(data['tuning']))
    receipts=[];batches=0;queries=0
    for seed in SEEDS:
        parent_file,parent_rows=generate(cfg['parents'][str(seed)],sources,output/f'parent-{seed}.json',kind='parent_coupled')
        batches+=parent_rows['encoder_batch_forwards'];queries+=parent_rows['encoder_source_evaluations']
        for arm in runtime.ARMS:
            name=f'{arm}-{seed}'
            file,payload=generate(initial['models'][name],sources,output/(name+'.json'))
            require(len(payload['rows'])==len(parent_rows['rows'])==288,'complete tuning parity required')
            for actual,expected in zip(payload['rows'],parent_rows['rows']):
                require(all(actual.get(k)==v for k,v in expected.items()),'initial inherited prediction differs')
            receipts.append({'trial':name,'generation':file,'parent_generation':parent_file,'queries':288,'inherited_fields_exact':True})
            batches+=payload['encoder_batch_forwards'];queries+=payload['encoder_source_evaluations']
    require(batches==48 and queries==2304,'actual parity counters differ')
    return write(output/'parity-frozen.json',{'schema':'legal-temporal-relative-owner-prefit-parity/v1',
        'config':pin,'initialization':initial_pin,'comparisons':receipts,'producer_pins':producer_pins(),
        'encoder_batch_forwards':batches,'encoder_source_evaluations':queries,'optimizer_updates':0,
        'fresh_reference_guard':guard_receipt(),'all_inherited_predictions_exact':True})


def fit_trial(config_path,initial_pin,sources,output,name):
    install_guard(config_path);cfg,pin,data=load_config(config_path);initial=read(initial_pin)
    require(initial['config']==pin,'initial config binding changed')
    directory=Path(output)/name;directory.mkdir(parents=True,exist_ok=False)
    cp=runtime.load_checkpoint(initial['models'][name]['path'],expected_sha256=initial['models'][name]['sha256'])
    stage_rows=[];reports=[];prior_steps=0
    for steps in STAGES:
        if steps:
            cp,report=runtime.train(cp,data['training'],data['tuning'],training_contrasts=data['training_other_norm_contrasts'],additional_steps=steps-prior_steps,max_seconds=1800)
            reports.append(write(directory/f'training-{steps}.json',report))
            runtime.save_checkpoint(cp,directory/f'checkpoint-{steps}.json')
            checkpoint=ref(directory/f'checkpoint-{steps}.json')
        else:checkpoint=initial['models'][name]
        generation,payload=generate(checkpoint,sources['tuning'],directory/f'tuning-{steps}.json')
        score=metrics.score(read(sources['tuning']),payload['rows'],target_map(data['tuning']))
        stage_rows.append({'steps':steps,'checkpoint':checkpoint,'tuning_generation':generation,
            'tuning_metrics':{k:v for k,v in score.items() if k!='rows'}})
        prior_steps=steps
        print(json.dumps({'phase':'stage','trial':name,'steps':steps,'joint_correct':score['joint_correct']}),flush=True)
    chosen=select(stage_rows)
    result={'name':name,'arm':cp['config']['arm'],'seed':cp['config']['seed'],'stages':stage_rows,'training_reports':reports,
            'selected_steps':chosen['steps'],'selected_checkpoint':chosen['checkpoint'],
            'selection_rule':'tuning_joint_correct_desc_selection_nll_asc_earlier_step','fresh_results_used':False,'calibration_results_used':False,
            'fresh_reference_guard':guard_receipt()}
    return write(directory/'trial-frozen.json',result)


def run(config_path,initial_path,output,workers=2):
    install_guard(config_path);cfg,pin,data=load_config(config_path);initial_pin=ref(initial_path);initial=read(initial_pin)
    require(initial['config']==pin and initial['producer_pins']==producer_pins(),'frozen initialization differs')
    require(workers in (1,2),'bounded worker count required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    targets={'training':data['training'],'tuning':data['tuning'],**data['retention_targets']}
    sources={name:write(output/'sources'/(name+'.json'),runtime.source_queries(rows)) for name,rows in targets.items()}
    for name in ALL_PANELS:sources[name]=write(output/'sources'/(name+'.json'),data[name+'_sources'])
    if cfg['diagnostic_sources'] is not None:sources['statutory_diagnostics']=cfg['diagnostic_sources']
    trials=[]
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        jobs=[pool.submit(fit_trial,config_path,initial_pin,sources,str(output),name) for name in sorted(initial['models'])]
        for job in as_completed(jobs):trials.append(job.result())
    trials=sorted(trials,key=lambda p:p['path']);trial_rows=[read(p) for p in trials]
    selection=write(output/'selections-frozen.json',{'schema':SCHEMA,'config':pin,'initialization':initial_pin,
        'trials':trial_rows,'trial_files':trials,'fresh_reference_guard':guard_receipt(),'fresh_results_used':False,'calibration_results_used':False})
    # Evaluation follows the already written selection freeze, with no feedback.
    physical={};logical=[]
    def job(slot,role,trial,checkpoint,panel,kind):
        key=hashlib.sha256(json.dumps([checkpoint['sha256'],sources[panel]['sha256'],kind]).encode()).hexdigest()
        if key not in physical:
            file,_=generate(checkpoint,sources[panel],output/'generations'/(key+'.json'),kind=kind)
            physical[key]=file
        logical.append({'slot':slot,'role':role,'trial':trial,'panel':panel,'checkpoint':checkpoint,
                        'decoder_kind':kind,'generation_key':key,'generation':physical[key]})
    for trial in trial_rows:
        final=trial['stages'][-1]['checkpoint'];name=trial['name']
        for panel in (*data['retention_targets'],*ALL_PANELS):
            job(name+'__selected','selected',name,trial['selected_checkpoint'],panel,'relative_owner')
        job(name+'__final200','final200',name,final,'training','relative_owner')
        if 'statutory_diagnostics' in sources:
            job(name+'__selected','selected',name,trial['selected_checkpoint'],'statutory_diagnostics','relative_owner')
    for seed in SEEDS:
        for panel in ('tuning',*data['retention_targets'],*ALL_PANELS):
            job(f'parent-{seed}','parent',None,cfg['parents'][str(seed)],panel,'parent_coupled')
    payload={'schema':SCHEMA,'config':pin,'initialization':initial_pin,'selections':selection,'sources':sources,
        'logical_generations':logical,'physical_generations':physical,'producer_pins':producer_pins(),
        'optimizer_updates':1200,'supervised_query_draws':28800,'final_generation_files':len(physical),
        'fresh_reference_guard':guard_receipt(),'all_training_selection_and_generation_complete':True,
        'pipeline_promotion':False,'latent_input_enabled':False,'statutory_semantics_verified':False}
    return write(output/'generation-frozen.json',payload)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('initialize','parity','fit'))
    p.add_argument('--config',required=True);p.add_argument('--output',required=True);p.add_argument('--initialization')
    p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    if a.phase=='initialize':result=initialize(a.config,a.output)
    else:
        if not a.initialization:p.error('--initialization required for fit')
        result=parity(a.config,a.initialization,a.output) if a.phase=='parity' else run(a.config,a.initialization,a.output,a.workers)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
