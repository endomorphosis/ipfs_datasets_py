#!/usr/bin/env python3
"""Independent replay first, reference release second, for owner-type pilots.

Scoring is diagnostic on authored attachment declarations. It never changes a
checkpoint, decision threshold, scope guard, or formula acceptance policy.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import sys

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as metric
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_corpus as corpus
from scripts.ops.legal_ir import run_legal_temporal_ownership_head as runner

require = metric.require
ARMS = ('source_only', 'frozen_occurrence', 'finetune_occurrence')
SEEDS = (1730, 1731)
STEPS = (50, 100, 200)
PANELS = ('fresh_sources', 'multi_fresh_sources')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def reference(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(pin):
    require(type(pin) is dict and set(pin) == {'path', 'bytes', 'sha256'} and
            type(pin['path']) is str and type(pin['bytes']) is int and pin['bytes'] >= 0 and
            type(pin['sha256']) is str, 'closed type-strict file reference required')
    require(wire(reference(pin['path'])) == wire(pin), 'file reference changed: '+pin['path'])
    return json.loads(Path(pin['path']).read_bytes())


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False); handle.write('\n')
    return reference(path)


def producer_pins():
    return [reference(module.__file__) for module in (sys.modules[__name__], metric, corpus, runner)]


def generation(value, checkpoint, sources_pin, sources, *, arm, seed, step):
    require(value['schema'] == 'legal-temporal-owner-type-source-generation/v1', 'generation schema differs')
    require(wire(value['model']) == wire({'checkpoint': checkpoint, 'arm': arm, 'seed': seed, 'steps': step}),
            'generation model differs')
    require(wire(value['sources']) == wire(sources_pin), 'generation source binding differs')
    require(value['class_order'] == list(metric.CLASSES) and type(value['threshold']) is float and value['threshold'] == .8,
            'fixed taxonomy/threshold differs')
    require(all(value[key] is False for key in metric.FALSE_FIELDS | {'labels_supplied', 'source_id_used_as_feature', 'owner_or_cue_spans_supplied'}),
            'generation authority/input flags differ')
    require(value['source_text_conditioned'] is True and value['time_occurrence_conditioned'] is (arm != 'source_only'),
            'conditioning contract differs')
    require(type(value['encoder_batch_forwards']) is int and value['encoder_batch_forwards'] == math.ceil(len(sources)/48) and
            type(value['encoder_source_evaluations']) is int and value['encoder_source_evaluations'] == len(sources),
            'generation actual counters differ')
    require(type(value['rows']) is list and len(value['rows']) == len(sources) and
            [r['id'] for r in value['rows']] == [s['id'] for s in sources], 'complete ordered source inventory required')
    for source, row in zip(sources, value['rows']): metric.checked_prediction(source, row)
    return value['rows']


def inventory(freeze):
    require(freeze['all_training_selection_and_generation_complete'] is True and freeze['fresh_references_opened'] is False and
            freeze['fresh_reference_guard']['premature_read_attempts'] == 0, 'generation must finish with references sealed')
    config = read(freeze['config']); selections = read(freeze['selections']); initials = read(freeze['initialization_freeze'])
    require(wire(selections['config']) == wire(freeze['config']) == wire(initials['config']) and
            wire(selections['initialization_freeze']) == wire(freeze['initialization_freeze']), 'freeze chain differs')
    require(selections['fresh_references_opened'] is False and selections['no_pipeline_promotion'] is True,
            'selection reference/promotion contract differs')
    require(wire(freeze['producer_pins']) == wire(runner.producer_pins()), 'frozen producer closure changed')
    expected_trials = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    trials = {t['name']: t for t in selections['trials']}
    require(len(trials) == len(selections['trials']) == 6 and set(trials) == expected_trials, 'six unique matched trials required')
    actual_trials = {t['name']: t for t in (read(p) for p in selections['trial_references'])}
    require(wire(actual_trials) == wire(trials) and len(selections['trial_references']) == 6, 'trial reference binding differs')
    for name, trial in trials.items():
        require(name == f"{trial['arm']}-{trial['seed']}" and type(trial['seed']) is int and
                trial['fresh_references_opened'] is False and trial['fresh_reference_guard']['premature_read_attempts'] == 0,
                'trial identity/seal differs')
        require(wire([s['steps'] for s in trial['stages']]) == wire(list(STEPS)), 'all stages required')
        require(wire(trial['initial_checkpoint']) == wire(initials['models'][name]), 'initial checkpoint differs')
        read_producer(trial['initial_checkpoint'])
        for stage in trial['stages']:
            read_producer(stage['checkpoint']); read_producer(stage['training_report'])
        selected = [s for s in trial['stages'] if s['steps'] == trial['selected_steps']]
        require(len(selected) == 1 and wire(selected[0]['checkpoint']) == wire(trial['selected_checkpoint']), 'selected checkpoint differs')
    sources = {k: read(v) for k, v in freeze['sources'].items()}
    require(set(sources) == {'training', 'tuning', *PANELS}, 'four source panels required')
    for panel, count in [('training', 768), ('tuning', 144), ('fresh_sources', 192), ('multi_fresh_sources', 96)]:
        corpus.validate_query_inventory(sources[panel], expected=count)
    slots = freeze['logical_generations']; seen = set(); unique = {}; physical = []
    expected = {(name, role, panel) for name in trials for role in ('selected', 'final200') for panel in PANELS}
    for slot in slots:
        name = f"{slot['arm']}-{slot['seed']}"; identity = (name, slot['role'], slot['panel'])
        require(identity in expected and identity not in seen and slot['slot'] == name+'__'+slot['role'], 'unknown/duplicate generation slot')
        seen.add(identity); trial = trials[name]
        cp = trial['selected_checkpoint'] if slot['role'] == 'selected' else trial['stages'][-1]['checkpoint']
        require(wire(slot['checkpoint']) == wire(cp), 'slot checkpoint differs')
        key = digest({'checkpoint': cp['sha256'], 'sources': freeze['sources'][slot['panel']]['sha256']})
        require(slot['generation_key'] == key and slot['executed_here'] is (key not in unique), 'generation alias key/status differs')
        if key in unique:
            require(wire(unique[key]['generation']) == wire(slot['generation']), 'alias file differs')
        else:
            unique[key] = slot
            physical.append({'key': key, 'generation': slot['generation'], 'encoder_batch_forwards': math.ceil(len(sources[slot['panel']])/48),
                             'encoder_source_evaluations': len(sources[slot['panel']])})
    require(seen == expected and wire(physical) == wire(freeze['executed_generations']), 'complete physical generation inventory required')
    counters = {'logical_generation_slots': 24, 'physical_generation_files': len(physical), 'logical_fresh_query_rows': 3456,
                'physical_fresh_query_rows': sum(p['encoder_source_evaluations'] for p in physical),
                'physical_fresh_encoder_batch_forwards': sum(p['encoder_batch_forwards'] for p in physical),
                'training_encoder_batch_forwards': 1200, 'training_encoder_source_evaluations': 19200, 'total_optimizer_updates': 1200}
    for key, value in counters.items(): require(type(freeze[key]) is int and freeze[key] == value, 'freeze counter differs: '+key)
    require(wire(freeze['admitted_generation_counters']) == wire({'encoder_batch_forwards': 456, 'encoder_source_evaluations': 21888}),
            'admitted generation counters differ')
    return config, trials, sources, unique, counters


def replay(freeze_path, output):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_ownership_head as runtime
    freeze_pin = reference(freeze_path); freeze = read(freeze_pin)
    guard = runner.install_fresh_reference_guard(freeze['config']['path'])
    runner.load_config(freeze['config']['path'])
    _, trials, sources, unique, counters = inventory(freeze)
    rows = []; batches = queries = 0
    for key, slot in unique.items():
        trial = trials[f"{slot['arm']}-{slot['seed']}"]
        step = trial['selected_steps'] if slot['role'] == 'selected' else 200
        source = sources[slot['panel']]; saved = read(slot['generation'])
        expected = generation(saved, slot['checkpoint'], freeze['sources'][slot['panel']], source,
                              arm=slot['arm'], seed=slot['seed'], step=step)
        cp = runtime.load_checkpoint(slot['checkpoint']['path'], expected_sha256=slot['checkpoint']['sha256'])
        model = runtime.TemporalOwnershipHead(cp); replayed = []
        for begin in range(0, len(source), 48): replayed.extend(model.predict_many(source[begin:begin+48]))
        require(wire(replayed) == wire(expected), 'independent checkpoint replay differs')
        batches += model.encoder_batch_forwards; queries += model.encoder_source_evaluations
        rows.append({'key': key, 'checkpoint': slot['checkpoint'], 'sources': freeze['sources'][slot['panel']],
                     'generation': slot['generation'], 'rows_sha256': digest(replayed), 'exact_rows': len(replayed),
                     'encoder_batch_forwards': model.encoder_batch_forwards, 'encoder_source_evaluations': model.encoder_source_evaluations})
        print(json.dumps({'replayed': len(rows), 'of': len(unique), 'exact_rows': len(replayed)}), flush=True)
    require(queries == counters['physical_fresh_query_rows'] and batches == counters['physical_fresh_encoder_batch_forwards'], 'replay counters differ')
    require(not runner._GUARD_STATE['attempts'], 'premature reference read attempted')
    return write(output, {'schema': 'legal-temporal-owner-type-independent-replay/v1', 'generation_freeze': freeze_pin,
        'replays': rows, 'exact_replay': True, 'encoder_batch_forwards': batches, 'encoder_source_evaluations': queries,
        'fresh_references_opened': False, 'fresh_reference_guard': guard, 'producer_files': producer_pins(),
        'pipeline_promotion': False})


def reconcile_metrics(actual, reported):
    mapping = {'count': 'count', 'correct': 'correct', 'accuracy': 'accuracy', 'macro_f1': 'macro_f1',
        'mean_nll': 'nll', 'multiclass_brier_sum': 'brier', 'ece_10_equal_width_bins': 'ece_10',
        'accepted_type_proposals': 'accepted', 'accepted_type_errors': 'accepted_wrong', 'type_proposal_coverage': 'coverage',
        'selective_type_error_rate': 'selective_risk', 'ambiguous_queries': 'ambiguous_support',
        'ambiguous_confidently_resolved': 'ambiguous_confident_errors'}
    for ours, theirs in mapping.items():
        a, b = actual[ours], reported[theirs]
        if type(a) is float:
            tolerance = 2e-6 if ours in ('multiclass_brier_sum', 'ece_10_equal_width_bins') else 1e-10
            require(type(b) in (int, float) and math.isfinite(b) and abs(a-b) <= tolerance, 'independent metric differs: '+ours)
        else: require(wire(a) == wire(b), 'independent metric differs: '+ours)
    require(wire(actual['confusion_target_rows_prediction_columns']) == wire(reported['confusion']), 'confusion differs')
    for label in metric.CLASSES:
        for key in ('support', 'correct', 'f1'):
            require(abs(actual['per_class'][label][key]-reported['per_class'][label][key]) < 1e-12, 'per-class score differs')


def score(freeze_path, replay_path, output):
    freeze_pin = reference(freeze_path); freeze = read(freeze_pin); replay_pin = reference(replay_path); replayed = read(replay_pin)
    require(replayed['schema'] == 'legal-temporal-owner-type-independent-replay/v1' and replayed['exact_replay'] is True and
            wire(replayed['generation_freeze']) == wire(freeze_pin) and replayed['fresh_references_opened'] is False and
            replayed['fresh_reference_guard']['premature_read_attempts'] == 0, 'source-only replay must precede reference release')
    for pin in replayed['producer_files']: read_producer(pin)
    config, trials, sources, unique, counters = inventory(freeze)
    require(len(replayed['replays']) == len(unique) and {r['key'] for r in replayed['replays']} == set(unique), 'incomplete replay receipt')
    for receipt in replayed['replays']:
        slot = unique[receipt['key']]; saved = read(slot['generation'])
        require(wire(receipt['generation']) == wire(slot['generation']) and wire(receipt['checkpoint']) == wire(slot['checkpoint']) and
                wire(receipt['sources']) == wire(saved['sources']) and receipt['rows_sha256'] == digest(saved['rows']) and
                receipt['exact_rows'] == len(saved['rows']), 'replay binding differs')
    require(replayed['encoder_batch_forwards'] == counters['physical_fresh_encoder_batch_forwards'] and
            replayed['encoder_source_evaluations'] == counters['physical_fresh_query_rows'], 'replay actual counters differ')
    manifest = read(config['corpus_manifest']); artifacts = manifest['artifacts']
    targets = {'training': read(artifacts['train_targets']), 'tuning': read(artifacts['tuning_targets'])}
    for panel, split in [('training', 'train'), ('tuning', 'tuning')]:
        groups = read(artifacts[split+'_groups'])
        corpus.validate_panel(targets[panel], groups, split)
        require(wire([corpus.source_row(r) for r in targets[panel]]) == wire(sources[panel]), 'released targets/source order differs')
    labels = {k: {r['id']: r['label'] for r in v} for k, v in targets.items()}
    admitted = []; selected_steps = {}; all_scores = {}; stages_scored = {}
    for name, trial in sorted(trials.items()):
        ranked = []
        for step in (0, *STEPS):
            stage = None if step == 0 else next(s for s in trial['stages'] if s['steps'] == step)
            cp = trial['initial_checkpoint'] if step == 0 else stage['checkpoint']
            panel_scores = {}
            for panel in ('training', 'tuning'):
                evidence = trial['initial_evaluation'][panel] if step == 0 else {'generation': stage[panel+'_generation'], 'metrics': stage[panel+'_metrics']}
                value = read(evidence['generation'])
                predictions = generation(value, cp, freeze['sources'][panel], sources[panel], arm=trial['arm'], seed=trial['seed'], step=step)
                result = metric.score(sources[panel], predictions, labels[panel]); reconcile_metrics(result, evidence['metrics'])
                panel_scores[panel] = {k: v for k, v in result.items() if k != 'rows'}
            admitted.append({'trial': name, 'steps': step, 'checkpoint': cp, 'scores': panel_scores})
            stages_scored[(name, step)] = panel_scores
            if step: ranked.append((-panel_scores['tuning']['macro_f1'], panel_scores['tuning']['mean_nll'], step))
        chosen = min(ranked)[2]; require(chosen == trial['selected_steps'], 'independent tuning selection differs')
        selected_steps[name] = chosen
    # Sole reference-release point: replay, byte integrity, admitted metric
    # reconstruction and independent tuning selection must all succeed first.
    ledger = read(artifacts['fresh_annotation_ledger']); read(artifacts['exposure_audit'])
    for panel, split in [('fresh_sources', 'fresh'), ('multi_fresh_sources', 'multi_fresh')]:
        targets[panel] = read(artifacts[split+'_targets'])
        corpus.validate_panel(targets[panel], ledger['groups'][split], split)
        require(wire([corpus.source_row(r) for r in targets[panel]]) == wire(sources[panel]), 'released targets/source order differs')
        labels[panel] = {r['id']: r['label'] for r in targets[panel]}
    physical_scores = {}
    for key, slot in unique.items():
        trial = trials[f"{slot['arm']}-{slot['seed']}"]; step = trial['selected_steps'] if slot['role'] == 'selected' else 200
        value = read(slot['generation']); source = sources[slot['panel']]
        predictions = generation(value, slot['checkpoint'], freeze['sources'][slot['panel']], source, arm=slot['arm'], seed=slot['seed'], step=step)
        result = metric.score(source, predictions, labels[slot['panel']])
        diagnostic = metric.occurrence_diagnostics(source, predictions, labels[slot['panel']], require_query_invariance=slot['arm'] == 'source_only')
        physical_scores[key] = {'generation': slot['generation'], 'metrics': result, 'occurrence_diagnostics': diagnostic}
    logical = [{**slot, 'metrics': {k: v for k, v in physical_scores[slot['generation_key']]['metrics'].items() if k != 'rows'},
                'occurrence_summary': {k: v for k, v in physical_scores[slot['generation_key']]['occurrence_diagnostics'].items() if k != 'groups'}}
               for slot in freeze['logical_generations']]
    comparisons = []
    for seed in SEEDS:
        for panel in PANELS:
            selected = {r['arm']: r for r in logical if r['seed'] == seed and r['panel'] == panel and r['role'] == 'selected'}
            for arm in ('frozen_occurrence', 'finetune_occurrence'):
                a = physical_scores[selected['source_only']['generation_key']]['metrics']; b = physical_scores[selected[arm]['generation_key']]['metrics']
                by_id = {r['id']: r for r in a['rows']}; paired = [(by_id[r['id']], r) for r in b['rows']]
                comparisons.append({'seed': seed, 'panel': panel, 'baseline': 'source_only', 'arm': arm, 'count': a['count'],
                    'correct_delta': b['correct']-a['correct'], 'fixed': sum(not x['correct'] and y['correct'] for x,y in paired),
                    'regressed': sum(x['correct'] and not y['correct'] for x,y in paired),
                    'accepted_type_error_delta': b['accepted_type_errors']-a['accepted_type_errors']})
    return write(output, {'schema': 'legal-temporal-owner-type-independent-score/v1', 'generation_freeze': freeze_pin,
        'replay_freeze': replay_pin, 'producer_files': producer_pins(), 'reference_release_after_replay': True,
        'released_references': [artifacts[k] for k in runner.SEALED_KEYS], 'admitted_scores': admitted,
        'independently_selected_steps': selected_steps, 'physical_fresh_scores': physical_scores, 'logical_fresh_scores': logical,
        'paired_selected_comparisons': comparisons, 'counters': counters, 'admitted_saved_query_rows_scored': 21888,
        'extra_replay_encoder_batch_forwards': replayed['encoder_batch_forwards'],
        'extra_replay_source_evaluations': replayed['encoder_source_evaluations'],
        'independent_legal_gold': False, 'owner_occurrence_resolved': False, 'pipeline_promotion': False,
        'admitted_outputs_numerically_replayed': False, 'exposure_claims_independently_audited_here': False,
        'latent_conditioning_improvement_tested': False, 'attachment_or_formula_acceptance_measured': False})


def read_producer(pin):
    require(type(pin) is dict and set(pin) == {'path', 'bytes', 'sha256'} and type(pin['bytes']) is int,
            'closed type-strict byte reference required')
    require(wire(reference(pin['path'])) == wire(pin), 'saved evidence or producer changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['replay', 'score']); parser.add_argument('--generation-freeze', required=True)
    parser.add_argument('--replay-freeze'); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.phase == 'replay': result = replay(args.generation_freeze, args.output)
    else:
        parser.error('--replay-freeze is required for score') if not args.replay_freeze else None
        result = score(args.generation_freeze, args.replay_freeze, args.output)
    print(json.dumps(result), flush=True)


if __name__ == '__main__': main()
