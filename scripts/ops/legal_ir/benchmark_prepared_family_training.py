#!/usr/bin/env python3
"""Paired CPU timing of v2/prepared native family feature reconstruction.

Inputs are previously prepared, source-bound training and tuning reports only.
The benchmark never reads a heldout panel or grants semantic qualification.
Each pair requires exact selected weights, observed loss/selection history,
inference, and a fresh-Adam continuation from the persisted complete parent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import time

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_v2 as reference
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_prepared as prepared

SCHEMA = 'prepared-family-throughput/v1'
FALSE = {'qualified':False,'admitted':False,'formalized':False,'promotion_performed':False,
         'heldout_used':False,'source_text_decoder_trained':False,'lake_build_executed':False}


def digest(raw): return hashlib.sha256(raw).hexdigest()


def save(path,value):
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()
    with path.open('xb') as stream: stream.write(raw)
    return {'path':str(path.resolve()),'sha256':digest(raw)}


def pins():
    return {str(Path(module.__file__).resolve()):digest(Path(module.__file__).read_bytes())
            for module in (codec,reference,prepared)} | {str(Path(__file__).resolve()):digest(Path(__file__).read_bytes())}


def comparable(report):
    return {key:value for key,value in report.items()
            if key not in {'schema','elapsed_seconds','prepared_execution','parent_descriptor'}}


def require_exact(one,two):
    if one['report']['optimizer_steps'] <= 0 or two['report']['optimizer_steps'] <= 0:
        raise ValueError('comparison requires actual optimizer updates on both arms')
    if comparable(one['report']) != comparable(two['report']):
        raise ValueError('reference/prepared observed loss or selection history differs')
    a,_=reference._read(one['descriptor']); b,_=prepared._read(two['descriptor'])
    if a['space'] != b['space'] or a['parameters'] != b['parameters']:
        raise ValueError('reference/prepared complete selected parameters differ')
    return {'selected_parameters_sha256':one['report']['selected_parameters_sha256'],
            'complete_parameters_exact':True,'feature_space_exact':True,'loss_selection_history_exact':True}


def inference_exact(one,two,validation):
    a=reference.infer_family_projection_autoencoder_v2(one['descriptor'],validation)
    b=prepared.infer_family_projection_autoencoder_prepared(two['descriptor'],validation)
    omit={'schema','checkpoint_sha256'}
    if {k:v for k,v in a.items() if k not in omit}!={k:v for k,v in b.items() if k not in omit}:
        raise ValueError('persisted inference differs')
    return True


def summarize(rows,backend):
    values=[row[backend]['wall_seconds'] for row in rows]
    presentations=sum(row[backend]['optimizer_row_presentations'] for row in rows)
    steps=sum(row[backend]['optimizer_steps'] for row in rows)
    return {'seconds_mean':statistics.mean(values),'seconds_sample_stddev':statistics.stdev(values) if len(values)>1 else 0.,
            'seconds_min':min(values),'seconds_max':max(values),'optimizer_steps_per_second':steps/sum(values),
            'optimizer_row_presentations_per_second':presentations/sum(values)}


def require_budget(report, epochs, training_rows, minibatch_size):
    expected_steps = epochs * ((training_rows + minibatch_size - 1) // minibatch_size)
    if (report['epochs_completed'] != epochs or report['optimizer_steps'] != expected_steps
            or report['stopping'] not in ('epoch_budget', 'validation_patience')):
        raise ValueError('timed arm did not finish the identical update budget')


def run(input_path,input_sha256,output_dir,*,epochs=256,repetitions=3,minibatch_size=6):
    import torch
    for key,expected in {'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}.items():
        if os.environ.get(key)!=expected: raise ValueError('set CPU startup environment '+key+'='+repr(expected))
    if not 1<=epochs<=256 or not 1<=repetitions<=7: raise ValueError('bounded epochs/repetitions required')
    source=pins(); raw=Path(input_path).read_bytes()
    if digest(raw)!=input_sha256: raise ValueError('fixed training/tuning input digest differs')
    inputs=json.loads(raw)
    if set(inputs)!={'training','validation'}: raise ValueError('only explicit training/validation reports allowed')
    training,validation=inputs['training'],inputs['validation']
    reference._reports(training); reference._reports(validation)
    output=Path(output_dir).resolve()
    if output.exists(): raise ValueError('fresh benchmark output required')
    output.mkdir(parents=True)
    settings=dict(epochs=epochs,latent_width=8,learning_rate=.001,minibatch_size=minibatch_size,
                  denoising=.05,ridge=.001,patience=epochs,seed=1729,max_seconds=120)
    environment={key:os.environ.get(key) for key in ('CUDA_VISIBLE_DEVICES','OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')}
    plan={'schema':SCHEMA,'input':{'path':str(Path(input_path).resolve()),'sha256':input_sha256},
          'sources':source,'settings':settings,'repetitions':repetitions,'order':'reference/prepared alternating AB/BA',
          'training_rows':len(training),'validation_rows':len(validation),'environment':environment,
          'scope':'identical native structural feature reconstruction; no source decoding',**FALSE}
    save(output/'plan.json',plan)
    calls={'reference':reference.train_family_projection_autoencoder_v2,
           'prepared':prepared.train_family_projection_autoencoder_prepared}
    torch.set_num_threads(1)
    for backend in calls:
        calls[backend](training,validation,output_dir=output/('warmup-'+backend),**{**settings,'epochs':1,'patience':1})
    pairs=[]
    for index in range(repetitions):
        pair={'repetition':index+1,'order':['reference','prepared'] if index%2==0 else ['prepared','reference']}
        results={}
        for backend in pair['order']:
            started=time.monotonic()
            result=calls[backend](training,validation,output_dir=output/f'pair-{index+1}-{backend}',**settings)
            elapsed=time.monotonic()-started
            report=result['report']
            require_budget(report,epochs,len(training),minibatch_size)
            results[backend]=result
            ref=save(output/f'pair-{index+1}-{backend}-result.json',result)
            pair[backend]={'wall_seconds':elapsed,'optimizer_steps':report['optimizer_steps'],
                           'optimizer_row_presentations':epochs*len(training),'result':ref,
                           'prepared_execution':report.get('prepared_execution')}
        pair['parity']=require_exact(results['reference'],results['prepared'])
        pair['parity']['persisted_inference_exact']=inference_exact(results['reference'],results['prepared'],validation)
        continuations={}
        for backend in calls:
            continuations[backend]=calls[backend](training,validation,output_dir=output/f'pair-{index+1}-{backend}-continuation',
                parent_descriptor=results[backend]['descriptor'],**{**settings,'epochs':1,'patience':1})
        pair['continuation']=require_exact(continuations['reference'],continuations['prepared'])
        pair['continuation']['scope']='complete parent weights, original fixed tuning panel, fresh Adam on both arms'
        pair['continuation']['persisted_inference_exact']=inference_exact(continuations['reference'],continuations['prepared'],validation)
        pair['speedup']=pair['reference']['wall_seconds']/pair['prepared']['wall_seconds']
        pairs.append(pair)
    if pins()!=source or digest(Path(input_path).read_bytes())!=input_sha256:
        raise ValueError('source/input changed during benchmark')
    report={**plan,'pairs':pairs,'summary':{key:summarize(pairs,key) for key in calls},
            'median_paired_speedup':statistics.median(pair['speedup'] for pair in pairs),
            'torch_threads':torch.get_num_threads(),'torch_interop_threads':torch.get_num_interop_threads(),
            'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'source_guard_passed':True,'all_exact':True,'performance_scope':'full public training call including setup and artifact validation',
            'cold_start_included':False,'native_target_preparation_included':False}
    save(output/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',required=True,type=Path)
    parser.add_argument('--inputs-sha256',required=True)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--epochs',type=int,default=256)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--minibatch-size',type=int,default=6)
    args=parser.parse_args()
    result=run(args.inputs,args.inputs_sha256,args.output_directory,epochs=args.epochs,
               repetitions=args.repetitions,minibatch_size=args.minibatch_size)
    print(json.dumps({'summary':result['summary'],'median_paired_speedup':result['median_paired_speedup'],
                      'all_exact':result['all_exact'],'peak_rss_bytes':result['peak_rss_bytes']}))


if __name__=='__main__': main()
