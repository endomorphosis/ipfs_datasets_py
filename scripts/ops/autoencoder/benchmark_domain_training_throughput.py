#!/usr/bin/env python3
"""Measure exact v2/prepared training throughput across four native IR domains.

Prepare only authored training/tuning sources, requesting the full family
inventory. Missing native families remain explicit gaps and receive no loss.
Run with CUDA_VISIBLE_DEVICES='' and OMP/MKL/OPENBLAS_NUM_THREADS=1 before Python.
Defaults: 3 alternating pairs/domain, 256 epochs, batch 6, 120 seconds per arm.
No heldout targets are prepared/read, and no quality or admission claim is made.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import statistics
import time

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel

_HELPER_PATH=Path(__file__).resolve().parents[1]/'legal_ir/benchmark_prepared_family_training.py'
_SPEC=importlib.util.spec_from_file_location('_domain_training_speed_pair',_HELPER_PATH)
paired=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(paired)
SCHEMA='multidomain-training-throughput/v1'
FALSE={**paired.FALSE,'heldout_targets_prepared':False,'selection_on_heldout':False,
       'source_semantics_verified':False,'provider_calls':0,'download_calls':0}


def _sha(raw): return hashlib.sha256(raw).hexdigest()


def _sources():
    return paired.pins() | {str(Path(__file__).resolve()):_sha(Path(__file__).read_bytes()),
                           str(Path(panel.__file__).resolve()):_sha(Path(panel.__file__).read_bytes())}


def _settings(domains,epochs,repetitions,minibatch_size):
    if (not isinstance(domains,(list,tuple)) or not domains or len(set(domains))!=len(domains)
            or not set(domains)<=set(panel.DOMAINS)):
        raise ValueError('unique supported domains required')
    if type(epochs) is not int or not 1<=epochs<=256:
        raise ValueError('epochs must be an integer in 1..256')
    if type(repetitions) is not int or not 1<=repetitions<=7:
        raise ValueError('repetitions must be an integer in 1..7')
    if type(minibatch_size) is not int or not 1<=minibatch_size<=1024:
        raise ValueError('minibatch size must be an integer in 1..1024')


def development_targets(domain):
    """The only target preparation boundary; never requests the test split."""
    if domain not in panel.DOMAINS: raise ValueError('supported domain required')
    return {'training':panel.prepare_partition(domain,'train'),
            'validation':panel.prepare_partition(domain,'validation')}


def _coverage(targets):
    reports=targets['training']+targets['validation']
    requested=reports[0]['requested_families']
    if any(row['requested_families']!=requested for row in reports):
        raise ValueError('fixed full family inventory required for every source')
    projections={row['projection_id']:row['logic_family'] for report in reports
                 for row in report['projections'] if row['ready_for_training']}
    return {'requested_family_ids':requested,'requested_family_count':len(requested),
            'ready_family_ids':sorted(set(projections.values())),
            'ready_projection_ids':sorted(projections),'ready_projection_count':len(projections),
            'scope':'actual ready native projections only; missing families stay masked gaps'}


def _timing_detail(result):
    prepared=[pair['prepared']['prepared_execution'] for pair in result['pairs']]
    reference_reports=[json.loads(Path(pair['reference']['result']['path']).read_bytes())['report']
                       for pair in result['pairs']]
    return {'full_public_training_call':result['summary'],
            'prepared_setup_including_initialization_and_calibration_seconds_mean':statistics.mean(
                row['preparation_seconds'] for row in prepared),
            'prepared_optimization_and_epoch_selection_seconds_mean':statistics.mean(
                row['optimization_seconds'] for row in prepared),
            'reference_after_feature_preparation_seconds_mean':statistics.mean(
                row['elapsed_seconds'] for row in reference_reports),
            'reference_subphase_limit':'reference timer includes initialization/calibration/optimization; no separate loop timer exists',
            'rates_count':'optimizer row presentations, including repeated epochs; not unique spans or legal-IR bridge evaluates'}


def run(output_dir,*,domains=panel.DOMAINS,epochs=256,repetitions=3,minibatch_size=6):
    _settings(domains,epochs,repetitions,minibatch_size)
    environment={key:os.environ.get(key) for key in ('CUDA_VISIBLE_DEVICES','OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')}
    expected={'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    if environment!=expected: raise ValueError('CPU startup thread caps required before target preparation')
    output=Path(output_dir).resolve()
    if output.exists(): raise ValueError('fresh throughput output required')
    producer=_sources()
    started=time.perf_counter()
    output.mkdir(parents=True)
    plan={'schema':SCHEMA,'domains':list(domains),'epochs':epochs,'repetitions':repetitions,
          'minibatch_size':minibatch_size,'patience':epochs,'max_seconds_per_arm':120,
          'seed':1729,'environment':environment,'producer':producer,
          'order':'AB/BA/AB alternation, warmed reference/prepared per domain',
          'workload':'fixed authored native family training/tuning targets; all default inventory families requested',
          'scope':'structural feature reconstruction speed only; no source-language decoder training',**FALSE}
    paired.save(output/'plan.json',plan)
    domains_result={}
    for domain in domains:
        directory=output/domain;directory.mkdir()
        prepare_started=time.perf_counter()
        targets=development_targets(domain)
        coverage=_coverage(targets)
        input_ref=paired.save(directory/'training-tuning-native-reports.json',targets)
        preparation_seconds=time.perf_counter()-prepare_started
        source_count=sum(len(values) for values in targets.values())
        if _sources()!=producer: raise ValueError('source changed during development preparation')
        result=paired.run(input_ref['path'],input_ref['sha256'],directory/'paired',
            epochs=epochs,repetitions=repetitions,minibatch_size=minibatch_size)
        domains_result[domain]={'native_inputs':input_ref,'training_rows':len(targets['training']),
            'tuning_rows':len(targets['validation']),'native_target_preparation_seconds':preparation_seconds,
            'native_target_preparation_seconds_per_source':preparation_seconds/source_count,
            'native_target_preparation_in_public_fit_timing':False,'coverage':coverage,
            'paired_report':{'path':str(directory/'paired/report.json'),
                'sha256':_sha((directory/'paired/report.json').read_bytes())},
            'timing':_timing_detail(result),'median_paired_speedup':result['median_paired_speedup'],
            'ratio_of_mean_training_wall_times':result['summary']['reference']['seconds_mean']/result['summary']['prepared']['seconds_mean'],
            'all_exact':result['all_exact'],'continuation_scope':'full saved parent, original tuning, fresh Adam on both arms',**FALSE}
        paired.save(directory/'summary.json',domains_result[domain])
        print(json.dumps({'domain':domain,'all_exact':result['all_exact'],'summary':result['summary'],
                          'median_paired_speedup':result['median_paired_speedup']}),flush=True)
    if _sources()!=producer: raise ValueError('source changed during throughput benchmark')
    for item in domains_result.values():
        for ref in (item['native_inputs'],item['paired_report']):
            if _sha(Path(ref['path']).read_bytes())!=ref['sha256']:
                raise ValueError('input/result changed during domain comparison')
    report={**plan,'domains':domains_result,'source_guard_passed':True,
            'elapsed_seconds':time.perf_counter()-started,
            'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'hardware_scope':'one CPU training thread and startup BLAS caps; shared host, no exclusive capacity claim',
            'all_exact':all(item['all_exact'] for item in domains_result.values()),
            'setup_cost_caution':'short and long workloads can differ; retain/report short-run regressions separately',
            'bridge_names':[],'legal_ir_evaluate_provers':False,'legal_ir_target_count':0,
            'bridge_scope':'native precomputed target reconstruction; not a bridge-on inference timing'}
    paired.save(output/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--domains',nargs='+',choices=panel.DOMAINS,default=list(panel.DOMAINS))
    parser.add_argument('--epochs',type=int,default=256)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--minibatch-size',type=int,default=6)
    args=parser.parse_args()
    run(args.output_directory,domains=args.domains,epochs=args.epochs,
        repetitions=args.repetitions,minibatch_size=args.minibatch_size)


if __name__=='__main__': main()
