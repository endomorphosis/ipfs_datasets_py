#!/usr/bin/env python3
"""Placement-curriculum owner-TYPE continuation; fresh references stay sealed.

Selection includes the unchanged warm parent and preserves six admitted
panels per class, accepted-error identities and accepted-correct coverage. Training is source/query conditioned; logical aliases
are reused only at identical checkpoint and complete source-list hashes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import sys

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_placement as runtime
from scripts.ops.legal_ir import run_legal_paired_temporal_ownership as previous_runner
from ipfs_datasets_py.logic.autoformal import legal_temporal_placement_qualification as gates

SCHEMA = 'legal-placement-temporal-owner-type-experiment/v1'
CONFIG_SCHEMA = 'legal-placement-temporal-owner-type-config/v1'
SEEDS = (1730, 1731)
STAGES = (50, 100, 200)
PARENT_SHAS = {1730: '92c87bd786d14a73f49970eadac46d23956f0b7af66809fcb244e2cd91f4ffdb',
               1731: '924fd35ce1f43fd8e3fdd34afc1032211ed3794e95c647401a93ce9838b9b00b'}
SEALED_KEYS = ('fresh_lexical_targets', 'fresh_structural_targets', 'fresh_annotation_ledger', 'exposure_audit')
TRAIN_PANELS = ('single_training','prior_paired_training','placement_training')
ADMITTED = (*TRAIN_PANELS,*gates.PANELS)
FINAL_PANELS = ('fresh_lexical','fresh_structural')
_GUARD = {'paths': set(), 'attempts': [], 'installed': False}
require = runtime.require
digest = runtime.digest
reference = previous_runner.reference
read = previous_runner.read
write = previous_runner.write
metrics = previous_runner.metrics


def install_fresh_reference_guard(config_path):
    config = read(reference(config_path)); manifest = read(config['corpus_manifest'])
    paths = {str(Path(manifest['artifacts'][key]['path']).resolve()) for key in SEALED_KEYS}
    require(len(paths) == 4, 'four fresh semantic/evidence seals required')
    _GUARD['paths'].update(paths)
    if not _GUARD['installed']:
        def hook(event, args):
            if event != 'open' or not args or not isinstance(args[0], (str, bytes, os.PathLike)): return
            path = str(Path(os.fsdecode(args[0])).resolve())
            if path in _GUARD['paths']:
                _GUARD['attempts'].append(path)
                raise PermissionError('fresh reference sealed through generation freeze: ' + path)
        sys.addaudithook(hook); _GUARD['installed'] = True
    return guard_receipt()


def guard_receipt():
    return {'sealed_paths': sorted(_GUARD['paths']), 'premature_read_attempts': len(_GUARD['attempts'])}


def producer_pins():
    from scripts.ops.legal_ir import prepare_legal_temporal_placement_corpus as corpus
    from ipfs_datasets_py.logic.autoformal import legal_temporal_placement_corpus as schema
    result = runtime.producer_pins()
    for module in (previous_runner, corpus, schema, gates, gates.metric): result[str(Path(module.__file__).resolve())] = reference(module.__file__)['sha256']
    for pin in schema.producers(): result[pin['path']] = pin['sha256']
    result.update(previous_runner.producer_pins())
    result[str(Path(__file__).resolve())] = reference(__file__)['sha256']
    return result


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_temporal_placement_corpus as corpus
    pin = reference(path); config = read(pin)
    require(set(config) == {'schema', 'corpus_manifest', 'parents', 'study_design', 'producer_files'} and config['schema'] == CONFIG_SCHEMA,
            'closed paired ownership config required')
    require(set(config['parents']) == {str(seed) for seed in SEEDS}, 'exact two parent seeds required')
    parents = {}
    for seed in SEEDS:
        parent_ref = config['parents'][str(seed)]
        require(parent_ref['sha256'] == PARENT_SHAS[seed], 'exact frozen occurrence200 parent required')
        parents[seed] = read(parent_ref); runtime._warm_model(parents[seed], seed)
    read(config['study_design']); manifest = read(config['corpus_manifest'])
    for item in config['producer_files']: require(reference(item['path']) == item, 'producer file changed')
    pinned = {item['path']: item['sha256'] for item in config['producer_files']}
    require(all(pinned.get(path) == sha for path, sha in producer_pins().items()), 'complete producer dependency pins required')
    data = corpus.load_training_inputs(config['corpus_manifest']['path'])
    projected = {key: runtime.project_training_rows(data[key]) if not key.endswith('units') else data[key]
                 for key in runtime.INPUT_KEYS}
    runtime._splits(*(projected[key] for key in runtime.INPUT_KEYS))
    require([len(projected[key]) for key in TRAIN_PANELS] == [768,864,864]
            and len(projected['prior_sampling_units']) == len(projected['sampling_units']) == 72,
            'prospective fitting counts differ')
    for name in gates.RETENTION_PANELS:
        rows=runtime.project_training_rows(data['retention_targets'][name])
        require(len(rows)==gates.PANEL_COUNTS[name], 'retention inventory differs')
        if name in projected: require(runtime.span._raw(rows)==runtime.span._raw(projected[name]),'retention/runtime target mismatch')
        projected[name]=rows
    require(len(projected['placement_tuning'])==288,'new tuning inventory differs')
    sources={'fresh_lexical':data['fresh_lexical_sources'],'fresh_structural':data['fresh_structural_sources']}
    require(all(len(sources[key])==144 for key in FINAL_PANELS),'prospective fresh counts differ')
    return {'config':config,'config_ref':pin,'parents':parents,'manifest':manifest,**projected,**sources}


def training_args(inputs): return tuple(inputs[key] for key in runtime.INPUT_KEYS)


def stage_gates(candidate): return {panel:candidate[panel+'_gate_counts'] for panel in gates.PANELS}


def eligible(candidate,parent): return gates.candidate_eligibility(stage_gates(candidate),stage_gates(parent))['eligible']


def stage_rank(candidate): return gates.rank(candidate['placement_tuning_gate_counts'],candidate['steps'])


def selection_receipt(parent,stages):
    require(parent['steps']==0 and tuple(s['steps'] for s in stages)==STAGES,'all prospective candidate steps required')
    return gates.select_candidate({c['steps']:stage_gates(c) for c in [parent,*stages]})


def select_stage(parent,stages):
    selected=selection_receipt(parent,stages)['selected_steps']
    return next(c for c in [parent,*stages] if c['steps']==selected)


def load_decoder(checkpoint_pin,decoder_kind):
    module=runtime.previous if decoder_kind=='paired_owner_type' else runtime if decoder_kind=='placement_owner_type' else None
    require(module is not None,'declared owner-type checkpoint kind required')
    checkpoint=module.load_checkpoint(checkpoint_pin['path'],expected_sha256=checkpoint_pin['sha256'])
    cls=module.PairedTemporalOwnershipHead if decoder_kind=='paired_owner_type' else module.TemporalPlacementHead
    return checkpoint,cls(checkpoint)


def generate(checkpoint_pin,sources_pin,output,*,decoder_kind):
    checkpoint,model=load_decoder(checkpoint_pin,decoder_kind); sources=read(sources_pin);rows=[]
    for begin in range(0,len(sources),48):rows.extend(model.predict_many(sources[begin:begin+48]))
    gates.source_only_predictions(sources,rows)
    payload={'schema':'legal-temporal-owner-type-source-generation/v1',
      'model':{'checkpoint':checkpoint_pin,'decoder_kind':decoder_kind,'arm':checkpoint['config']['arm'],
               'seed':checkpoint['config']['seed'],'steps':checkpoint['optimizer_steps']},
      'sources':sources_pin,'class_order':list(runtime.CLASSES),'threshold':.8,'rows':rows,
      'encoder_batch_forwards':model.encoder_batch_forwards,'encoder_source_evaluations':model.encoder_source_evaluations,
      'labels_supplied':False,'source_text_conditioned':True,'time_occurrence_conditioned':True,
      'source_id_used_as_feature':False,'owner_or_cue_spans_supplied':False,**runtime.FALSE}
    return write(output,payload),payload


def evaluate_panel(panel,payload,inputs):
    result={'metrics':metrics(payload['rows'],inputs[panel])}
    if panel in gates.PANELS:
        scored=gates.panel_metrics(runtime.source_queries(inputs[panel]),payload['rows'],{r['id']:r['label'] for r in inputs[panel]})
        result['gate_counts']=scored['gate_counts']
    return result


def prepare_initials(config_path, output):
    install_fresh_reference_guard(config_path); inputs = load_config(config_path)
    output = Path(output); require(not output.exists(), 'new initialization directory required'); output.mkdir(parents=True)
    models, states = {}, {}
    for seed in SEEDS:
        for arm in runtime.ARMS:
            name = f'{arm}-{seed}'
            cp = runtime.build_checkpoint(inputs['parents'][seed], *training_args(inputs), arm=arm, seed=seed,
                                          parent_file_sha256=inputs['config']['parents'][str(seed)]['sha256'])
            models[name] = runtime.save_checkpoint(cp, output / f'{name}.json'); states[name] = cp['initial_state_sha256']
        require(len({states[f'{arm}-{seed}'] for arm in runtime.ARMS}) == 1, 'matched arm initial states differ')
        require(states[f'{runtime.ARMS[0]}-{seed}'] == digest(inputs['parents'][seed]['model_state']), 'warm parent tensors differ')
    result = write(output / 'initialization-frozen.json', {'schema': SCHEMA, 'config': inputs['config_ref'],
        'models': models, 'initial_state_digests': states, 'parents': inputs['config']['parents'],
        'manifests': runtime._manifests(*training_args(inputs)), 'optimizer_steps': 0, 'parent_optimizer_moments_transferred': False,
        'fresh_references_opened': False, 'fresh_reference_guard': guard_receipt(), 'producer_pins': producer_pins()})
    print(json.dumps({'phase': 'initialization_frozen', 'reference': result}), flush=True); return result


def fit_trial(config_path, initial_freeze_pin, parent_evaluations, sources, output, name):
    install_fresh_reference_guard(config_path); inputs = load_config(config_path); initials = read(initial_freeze_pin)
    require(initials['config'] == inputs['config_ref'], 'initial config differs')
    output = Path(output) / name; output.mkdir(parents=True, exist_ok=False)
    initial = initials['models'][name]; checkpoint = runtime.load_checkpoint(initial['path'], expected_sha256=initial['sha256'])
    seed = checkpoint['config']['seed']; parent_ref = inputs['config']['parents'][str(seed)]
    parent = {'steps': 0, 'checkpoint': parent_ref, 'decoder_kind': 'paired_owner_type'}
    for panel in ADMITTED:
        evidence = parent_evaluations[str(seed)][panel]
        parent[panel + '_generation'] = evidence['generation']; parent[panel + '_metrics'] = evidence['metrics']
        if panel in gates.PANELS: parent[panel+'_gate_counts']=evidence['gate_counts']
    stages = []
    for step in STAGES:
        checkpoint, report = runtime.train(checkpoint, *training_args(inputs), additional_steps=step - checkpoint['optimizer_steps'], max_seconds=600)
        cp_pin = runtime.save_checkpoint(checkpoint, output / f'checkpoint-{step}.json')
        stage = {'steps': step, 'checkpoint': cp_pin, 'decoder_kind': 'placement_owner_type',
                 'training_report': write(output / f'training-{step}.json', report)}
        for panel in ADMITTED:
            pin, payload = generate(cp_pin, sources[panel], output / f'stage-{step}-{panel}.json', decoder_kind='placement_owner_type')
            stage[panel + '_generation'] = pin; evaluated=evaluate_panel(panel,payload,inputs); stage[panel+'_metrics']=evaluated['metrics']
            if panel in gates.PANELS:stage[panel+'_gate_counts']=evaluated['gate_counts']
        stage['eligible'] = eligible(stage, parent); stages.append(stage)
        print(json.dumps({'phase': 'stage', 'trial': name, 'steps': step, 'eligible': stage['eligible'],
            'single_tuning_correct': stage['single_tuning_metrics']['correct'], 'placement_tuning_correct':stage['placement_tuning_metrics']['correct'],
            'placement_tuning_macro_f1':stage['placement_tuning_metrics']['macro_f1']}), flush=True)
    selected = select_stage(parent, stages)
    return write(output / 'trial.json', {'schema': SCHEMA, 'name': name, 'arm': checkpoint['config']['arm'], 'seed': seed,
        'parent_checkpoint': parent_ref, 'initial_checkpoint': initial, 'initial_evaluation': parent_evaluations[str(seed)],
        'parent_candidate': parent, 'stages': stages, 'selected_steps': selected['steps'],
        'selected_checkpoint': selected['checkpoint'], 'selected_decoder_kind': selected['decoder_kind'],
        'selection': 'six_panel_perclass_correct_acceptedcorrect_error_ID_retention_plus_newclassfloor_then_macroF1_nll_earlier_parent0',
        'selection_receipt':selection_receipt(parent,stages),
        'selected_parent_fallback': selected['steps'] == 0, 'selected_is_pipeline_promotion': False,
        'fresh_references_opened': False, 'fresh_reference_guard': guard_receipt()})


def run(config_path, initials_path, output, *, workers=2):
    require(type(workers) is int and 1 <= workers <= 2, 'at most two one-thread CPU workers required')
    install_fresh_reference_guard(config_path); inputs = load_config(config_path)
    initials_pin = reference(initials_path); initials = read(initials_pin)
    require(initials['config'] == inputs['config_ref'] and initials['producer_pins'] == producer_pins(), 'initial freeze differs')
    output = Path(output); require(not output.exists(), 'new run output required'); output.mkdir(parents=True)
    sources = {panel: write(output / f'{panel}-sources.json', runtime.source_queries(inputs[panel]) if panel in ADMITTED else inputs[panel])
               for panel in (*ADMITTED, *FINAL_PANELS)}
    parent_evaluations = {}; admitted_counts = Counter()
    for seed in SEEDS:
        parent_evaluations[str(seed)] = {}
        for panel in ADMITTED:
            pin, payload = generate(inputs['config']['parents'][str(seed)], sources[panel], output / 'parent-evaluations' / f'{seed}-{panel}.json', decoder_kind='paired_owner_type')
            parent_evaluations[str(seed)][panel] = {'generation':pin,**evaluate_panel(panel,payload,inputs)}
            admitted_counts.update({key: payload[key] for key in ('encoder_batch_forwards', 'encoder_source_evaluations')})
    parents_pin = write(output / 'parent-evaluations-frozen.json', {'schema': SCHEMA, 'parents': inputs['config']['parents'],
        'evaluations': parent_evaluations, 'fresh_references_opened': False, 'fresh_reference_guard': guard_receipt()})
    names = [f'{arm}-{seed}' for seed in SEEDS for arm in runtime.ARMS]; trials = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = {pool.submit(fit_trial, config_path, initials_pin, parent_evaluations, sources, output, name): name for name in names}
        for future in as_completed(futures): trials.append(future.result())
    values = sorted([read(pin) for pin in trials], key=lambda item: item['name'])
    training_counts = Counter(); schedules = {}; traces = {}; exposures = {}
    for trial in values:
        trace = []
        for stage in trial['stages']:
            report = read(stage['training_report']); trace.extend(report['trace'])
            training_counts.update({key: report[key] for key in ('steps_executed', 'encoder_batch_forwards', 'encoder_source_evaluations')})
            for panel in ADMITTED:
                payload = read(stage[panel + '_generation'])
                admitted_counts.update({key: payload[key] for key in ('encoder_batch_forwards', 'encoder_source_evaluations')})
        require([row['step'] for row in trace] == list(range(1, 201)), 'complete ordered200-update trial required')
        traces[trial['name']] = trace
        schedules[trial['name']] = digest([{key: row[key] for key in ('query_ids','single_group_ids','prior_paired_unit_ids','placement_unit_ids')} for row in trace])
        counts = Counter(identity for row in trace for identity in row['query_ids'])
        old_ids={row['id'] for row in inputs['single_training']}
        prior_ids={row['id'] for row in inputs['prior_paired_training']}
        new_ids={row['id'] for row in inputs['placement_training']}
        exposures[trial['name']]={'query_draws':sum(counts.values()),'distinct_queries':len(counts),
          'distinct_single_queries':len(set(counts)&old_ids),'distinct_prior_paired_queries':len(set(counts)&prior_ids),
          'distinct_placement_queries':len(set(counts)&new_ids),'query_counts':dict(counts),
          'prior_paired_unit_counts':dict(Counter(i for row in trace for i in row['prior_paired_unit_ids'])),
          'placement_unit_counts':dict(Counter(i for row in trace for i in row['placement_unit_ids']))}
    for seed in SEEDS:
        for a,b in zip(traces[f'continuation-{seed}'],traces[f'placement-{seed}']):
            require(a['query_ids'][:12]==b['query_ids'][:12] and a['single_group_ids']==b['single_group_ids'],'shared single draws differ')
            if (a['step']-1)%2==0: require(a['query_ids']==b['query_ids'],'common even-step batch differs')
            else:require(a['pool_counts']=={'single':12,'prior_paired':12,'placement':0}
                         and b['pool_counts']=={'single':12,'prior_paired':0,'placement':12},'odd-step replacement differs')
    require(training_counts == {'steps_executed': 800, 'encoder_batch_forwards': 800, 'encoder_source_evaluations': 19200}, 'training totals differ')
    selections = write(output / 'selections-frozen.json', {'schema': SCHEMA, 'config': inputs['config_ref'], 'initialization_freeze': initials_pin,
        'parent_evaluations': parents_pin, 'trials': values, 'trial_references': sorted(trials, key=lambda pin: pin['path']),
        'training_exposures': exposures, 'training_schedule_sha256': schedules, 'total_optimizer_updates': 800,
        'fresh_references_opened': False, 'no_pipeline_promotion': True})
    slots = [{'slot': f'parent-{seed}', 'arm': 'parent', 'seed': seed, 'role': 'parent', 'additional_steps': 0,
              'checkpoint': inputs['config']['parents'][str(seed)], 'decoder_kind': 'paired_owner_type'} for seed in SEEDS]
    for trial in values:
        slots.extend([{'slot': trial['name'] + '__selected', 'arm': trial['arm'], 'seed': trial['seed'], 'role': 'selected',
                       'additional_steps': trial['selected_steps'], 'checkpoint': trial['selected_checkpoint'], 'decoder_kind': trial['selected_decoder_kind']},
                      {'slot': trial['name'] + '__final200', 'arm': trial['arm'], 'seed': trial['seed'], 'role': 'final200',
                       'additional_steps': 200, 'checkpoint': trial['stages'][-1]['checkpoint'], 'decoder_kind': 'placement_owner_type'}])
    cache = {}; logical = []; actual = []
    for slot in slots:
        for panel in FINAL_PANELS:
            key = digest({'checkpoint': slot['checkpoint']['sha256'], 'sources': sources[panel]['sha256']})
            executed = key not in cache
            if executed:
                pin, payload = generate(slot['checkpoint'], sources[panel], output / 'generations' / f'{key}.json', decoder_kind=slot['decoder_kind'])
                cache[key] = pin; actual.append({'key': key, 'generation': pin,
                    'encoder_batch_forwards': payload['encoder_batch_forwards'], 'encoder_source_evaluations': payload['encoder_source_evaluations']})
            logical.append({**slot, 'panel': panel, 'generation': cache[key], 'generation_key': key, 'executed_here': executed})
    result = write(output / 'generation-frozen.json', {'schema': SCHEMA, 'config': inputs['config_ref'], 'initialization_freeze': initials_pin,
        'parent_evaluations': parents_pin, 'selections': selections, 'sources': sources, 'producer_pins': producer_pins(),
        'logical_generations': logical, 'executed_generations': actual, 'logical_generation_slots': len(logical),
        'logical_fresh_query_rows': sum(len(inputs[row['panel']]) for row in logical),
        'physical_generation_files': len(actual), 'physical_fresh_query_rows': sum(row['encoder_source_evaluations'] for row in actual),
        'physical_fresh_encoder_batch_forwards': sum(row['encoder_batch_forwards'] for row in actual),
        'total_optimizer_updates': 800, 'training_encoder_batch_forwards': 800, 'training_encoder_source_evaluations': 19200,
        'admitted_generation_counters': dict(admitted_counts), 'fresh_references_opened': False,
        'fresh_reference_guard': guard_receipt(), 'all_training_selection_and_generation_complete': True,
        'models_are_unqualified_research_heads': True,
        'panel_roles':{'fresh_lexical':'new lexical holdout; shared layout families','fresh_structural':'new structural holdout'},
        'old_stream_note':'Three continuous old quartet draws shared; placement replaces odd zero-based old-paired slots with new placement units. Actual coverage recorded.'})
    print(json.dumps({'phase': 'generation_frozen', 'reference': result}), flush=True); return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--initials', type=Path); parser.add_argument('--prepare-initials', action='store_true')
    parser.add_argument('--workers', type=int, default=2); args = parser.parse_args(argv)
    if args.prepare_initials: return prepare_initials(args.config, args.output)
    require(args.initials is not None, 'frozen initial checkpoints required before fitting')
    return run(args.config, args.initials, args.output, workers=args.workers)


if __name__ == '__main__': main()
