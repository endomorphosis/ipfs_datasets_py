#!/usr/bin/env python3
"""Continue only the frozen boundary model's scope classifier, with raw gates.

No embedding, encoder or token-boundary parameters change. Scope eligibility is
selected independently of clause model predictions; a downstream abstention is
never evidence that the scope classifier correctly rejected an unsupported row.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as corpus
from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as old

boundary, clauses = old.boundary, old.clauses
require, digest = boundary.require, boundary.digest
read_ref, file_ref, write_new, sha = old.read_ref, corpus.file_ref, corpus.write_new, corpus.sha
SCHEMA = 'legal-scope-retention-experiment/v1'
CONFIG_SCHEMA = 'legal-scope-retention-config/v1'
ARMS = ('control', 'target')
STEPS = (100, 200, 400)
SEED = 1730
PARENT_SHA = 'e741578ac017e163588c6b49a16f6bca9dd0a37e71a0c345a3c9706814c3cf99'
SCOPE_PARAMETERS = {'scope.weight', 'scope.bias'}


def read_config(path):
    config = json.loads(Path(path).read_bytes())
    require(type(config) is dict and set(config) == {'schema', 'scope_corpus_manifest', 'boundary_parent',
        'prior_temporal_generation', 'additional_tuning_refs', 'additional_source_refs', 'study_design', 'producer_files'}
        and config['schema'] == CONFIG_SCHEMA, 'closed scope experiment config required')
    for key in ('scope_corpus_manifest', 'boundary_parent', 'prior_temporal_generation', 'study_design'):
        read_ref(config[key], parse=False)
    for reference in config['producer_files']: read_ref(reference, parse=False)
    require(config['boundary_parent']['sha256'] == PARENT_SHA, 'exact expanded1730 boundary parent required')
    parent = read_ref(config['boundary_parent']); boundary.restore(parent)
    frozen = read_ref(config['prior_temporal_generation'])
    require(frozen['all_training_selection_and_generation_complete'] is True, 'completed prior temporal generation required')
    pipelines = read_ref(frozen['pipeline_heads'])
    require(any(p['boundary_checkpoint']['sha256'] == PARENT_SHA for p in pipelines), 'boundary parent omitted from prior generation')
    loaded = corpus.load_training_inputs(config['scope_corpus_manifest']['path'])
    tuning = dict(loaded['tuning'])
    for name, ref in config['additional_tuning_refs'].items():
        require(name not in tuning, 'duplicate tuning panel name')
        rows = read_ref(ref)
        old.validate_references(rows, len(rows), sum(r['supported'] for r in rows))
        tuning[name] = rows
    sources = {name: clauses.source_rows(rows) for name, rows in tuning.items()}
    sources['scope_fresh'] = loaded['fresh_sources']
    for name, ref in config['additional_source_refs'].items():
        require(name not in sources, 'duplicate source panel name')
        rows = read_ref(ref); old.validate_sources(rows, len(rows)); sources[name] = rows
    historical = [r for rows in loaded['replay'].values() for r in rows]
    require(len(historical) == 576 and len({r['source_sha256'] for r in historical}) == 576, 'complete distinct replay corpus required')
    fit = historical + loaded['new_train']
    fit_hashes = {r['source_sha256'] for r in fit}
    require(len(fit_hashes) == 768, 'new boundary training must be disjoint from replay')
    for name, rows in sources.items():
        require(not fit_hashes & {r['source_sha256'] for r in rows}, 'scope fitting source overlaps evaluation: ' + name)
    return {'config': config, 'manifest': loaded['manifest'], 'parent': parent,
            'replay': historical, 'new_train': loaded['new_train'], 'training_pairs': loaded['training_pairs'],
            'tuning': tuning, 'sources': sources}


def frozen_state(value):
    return {k: v for k, v in value.items() if k not in SCOPE_PARAMETERS}


def assert_frozen_state(parent, candidate):
    require(set(candidate) == set(parent), 'boundary tensor inventory changed')
    require(frozen_state(parent) == frozen_state(candidate), 'frozen embedding/encoder/token-boundary state changed')
    return digest(frozen_state(candidate))


def configure_trainable(network):
    for name, parameter in network.named_parameters(): parameter.requires_grad_(name in SCOPE_PARAMETERS)
    names = {name for name, p in network.named_parameters() if p.requires_grad}
    require(names == SCOPE_PARAMETERS and sum(p.numel() for p in network.parameters() if p.requires_grad) == 130,
            'only the existing130 scope parameters may train')
    return [p for p in network.parameters() if p.requires_grad]


def batch_schedule(replay, new_train, pairs, arm, steps=400):
    require(arm in ARMS and type(steps) is int and 1 <= steps <= 400, 'declared scope arm and budget required')
    common = old.CyclingRows(replay, random.Random(SEED))
    positives = old.CyclingRows([r for r in replay if r['supported']], random.Random(SEED + 1))
    guards = old.CyclingRows([r for r in replay if not r['supported']], random.Random(SEED + 2))
    paired = old.CyclingRows(pairs, random.Random(SEED + 3))
    by_id = {r['candidate_id']: r for r in new_train}
    corpus.validate_pairs(new_train, pairs, 96)
    for step in range(1, steps + 1):
        left = common.take(6)
        selected_pairs = [] if arm == 'control' else paired.take(3)
        right = positives.take(3) + guards.take(3) if arm == 'control' else [
            by_id[p[key]] for p in selected_pairs for key in ('independent_id', 'nested_id')]
        require(sum(r['supported'] for r in right) == 3, 'matched extra batch scope class counts required')
        rows = left + right
        yield rows, {'steps': step, 'common_replay_ids': [r['candidate_id'] for r in left],
                     'extra_ids': [r['candidate_id'] for r in right], 'pair_ids': [p['pair_id'] for p in selected_pairs],
                     'supported_count': sum(r['supported'] for r in rows), 'unsupported_count': sum(not r['supported'] for r in rows)}


def metrics(generation, references):
    result = clauses.evaluate(generation, references)
    result['raw_unsupported_accepted'] = result.get('unsupported_documents', 0) - result.get('raw_unsupported_scope_correct', 0)
    result['raw_supported_rejected'] = result.get('supported_documents', 0) - result.get('raw_supported_scope_correct', 0)
    return result


def gates(stage_metrics, parent_metrics, raw_token_logits_unchanged):
    require(set(stage_metrics) == set(parent_metrics) and 'scope_new' in stage_metrics, 'all preregistered tuning panels required')
    failures = []
    if raw_token_logits_unchanged is not True: failures.append('token_boundary_logits_changed')
    for panel in sorted(stage_metrics):
        score, parent = stage_metrics[panel], parent_metrics[panel]
        require(score['documents'] == parent['documents'] and score['supported_documents'] == parent['supported_documents']
                and score['unsupported_documents'] == parent['unsupported_documents'], 'complete tuning scope denominators differ')
        for metric in ('raw_supported_scope_correct', 'exact_supported_segmentation'):
            if score.get(metric, 0) < parent.get(metric, 0): failures.append(panel + ':' + metric + '_regressed')
        if score['raw_unsupported_accepted'] != 0: failures.append(panel + ':raw_unsupported_accepted')
        if score.get('unsupported_accepted', 0) != 0: failures.append(panel + ':final_unsupported_accepted')
    return {'eligible': not failures, 'failures': failures}


def select_stage(stages):
    require(len(stages) == len(STEPS) and [s['steps'] for s in stages] == list(STEPS), 'all400 planned updates and three stages required')
    eligible = [s for s in stages if s['eligible']]
    def rank(stage):
        new = stage['metrics']['scope_new']
        return (new.get('raw_supported_scope_correct', 0), new.get('exact_supported_segmentation', 0),
                sum(m.get('exact_supported_segmentation', 0) for p, m in stage['metrics'].items() if p != 'scope_new'), -stage['steps'])
    return max(eligible, key=rank) if eligible else None


def decode(checkpoint, sources):
    decoder = boundary.ClauseBoundaryDecoder(checkpoint)
    return {panel: clauses.decode_all(decoder, rows) for panel, rows in sources.items()}


def assert_raw_token_identity(generation, parent_generation):
    require(len(generation['rows']) == len(parent_generation['rows']), 'token preservation denominator differs')
    for row, parent in zip(generation['rows'], parent_generation['rows']):
        require(row['candidate_id'] == parent['candidate_id'] and row['source_sha256'] == parent['source_sha256'], 'token preservation source join differs')
        require(row['boundary_logits'] == parent['boundary_logits'] and row['boundary_token_indices'] == parent['boundary_token_indices'],
                'raw token boundary output changed')
    return True


def run(config_path, output):
    import torch
    torch.set_num_threads(1)
    loaded = read_config(config_path)
    output = Path(output).resolve(); require(not output.exists(), 'new boundary run directory required'); output.mkdir(parents=True)
    plan = write_new(output / 'plan.json', {
        'schema': SCHEMA, 'config': file_ref(config_path), 'corpus': loaded['config']['scope_corpus_manifest'],
        'producer_pins': {str(Path(module.__file__).resolve()): sha(Path(module.__file__).read_bytes()) for module in (corpus, old, boundary, clauses)},
        'runner': file_ref(__file__), 'arms': list(ARMS), 'seed': SEED, 'stages': list(STEPS), 'steps_per_arm': 400,
        'trainable_parameters': sorted(SCOPE_PARAMETERS), 'trainable_parameter_count': 130,
        'learning_rate': .004, 'scope_class_weights': [3., 1.], 'optimizer': 'fresh_Adam',
        'gradient_clip_norm': 5., 'trial_wall_limit_seconds': 900,
        'common_replay_rows': 6, 'control_extra': '3historical_supported+3historical_guards', 'target_extra': '3new_scope_contrast_pairs',
        'scope_threshold_and_surface_policy_unchanged': True, 'clause_predictions_used_for_selection': False,
        'new_fresh_targets_opened': False, 'tuning_counts': {k: len(v) for k, v in loaded['tuning'].items()},
        'source_counts': {k: len(v) for k, v in loaded['sources'].items()},
        'replay_count': 576, 'new_training_count': 192, 'training_source_inventory_sha256': digest(loaded['replay'] + loaded['new_train']),
        'scope': 'Bounded authored scope eligibility continuation; no expanded logic profile or statutory independence proof.'})
    tuning_sources = {name: loaded['sources'][name] for name in loaded['tuning']}
    parent_generation = decode(loaded['parent'], tuning_sources)
    parent_metrics = {name: metrics(parent_generation[name], rows) for name, rows in loaded['tuning'].items()}
    parent_tuning = write_new(output / 'parent-tuning.json', {'generation': parent_generation, 'metrics': parent_metrics})
    trials = []
    for arm in ARMS:
        folder = output / arm; folder.mkdir(); torch.manual_seed(SEED)
        _, network = boundary.restore(loaded['parent']); optimizer = torch.optim.Adam(configure_trainable(network), lr=.004)
        initial_full_state_sha = digest({k: t.tolist() for k, t in network.state_dict().items()})
        require(initial_full_state_sha == digest(loaded['parent']['model_state']), 'scope continuation initialization differs from complete parent state')
        require(not optimizer.state and not optimizer.state_dict()['state'], 'fresh empty Adam state required')
        initial_sha = assert_frozen_state(loaded['parent']['model_state'], {k: t.tolist() for k, t in network.state_dict().items()})
        training_manifest = {'arm': arm, 'seed': SEED, 'plan': plan, 'steps': 400, 'only_scope_parameters': sorted(SCOPE_PARAMETERS),
                             'replay_sha256': digest(loaded['replay']), 'new_training_sha256': digest(loaded['new_train']) if arm == 'target' else None}
        stages, losses, batches = [], [], []
        started = time.monotonic()
        for rows, receipt in batch_schedule(loaded['replay'], loaded['new_train'], loaded['training_pairs'], arm):
            step = receipt['steps']; network.train(); optimizer.zero_grad(set_to_none=True)
            ids, features, lengths, _, scopes, _ = boundary.tensor_batch(torch, rows, labels=True)
            _, scope_logits = network(ids, features, lengths)
            loss = torch.nn.functional.cross_entropy(scope_logits, scopes, weight=torch.tensor([3., 1.]))
            require(bool(torch.isfinite(loss)), 'nonfinite scope continuation loss')
            loss.backward(); torch.nn.utils.clip_grad_norm_(network.scope.parameters(), 5.); optimizer.step()
            losses.append(float(loss.detach())); batches.append(receipt)
            require(time.monotonic() - started < 900., 'bounded scope trial wall budget exhausted')
            if step not in STEPS: continue
            checkpoint = boundary.checkpoint(network, steps=loaded['parent']['optimizer_steps'] + step,
                training_manifest_sha256=digest(training_manifest), tuning_manifest_sha256=digest(loaded['tuning']))
            require(assert_frozen_state(loaded['parent']['model_state'], checkpoint['model_state']) == initial_sha, 'frozen weights changed')
            checkpoint_ref = write_new(folder / f'checkpoint-{step}.json', checkpoint)
            generation = decode(checkpoint, tuning_sources)
            token_identity = all(assert_raw_token_identity(generation[name], parent_generation[name]) for name in generation)
            scores = {name: metrics(generation[name], rows) for name, rows in loaded['tuning'].items()}
            evaluated = write_new(folder / f'stage-{step}-tuning.json', {'generation': generation, 'metrics': scores})
            require(time.monotonic() - started < 900., 'scope trial wall budget exhausted during stage evaluation')
            stage = {'steps': step, 'checkpoint': checkpoint_ref, 'tuning': evaluated, 'metrics': scores,
                     'frozen_non_scope_state_sha256': initial_sha, 'raw_token_logits_unchanged': token_identity,
                     **gates(scores, parent_metrics, token_identity)}
            stages.append(stage)
            print(json.dumps({'arm': arm, 'steps': step, 'eligible': stage['eligible'], 'failures': stage['failures'],
                              'scope_new': {k: scores['scope_new'][k] for k in ('raw_supported_scope_correct', 'raw_unsupported_accepted', 'exact_supported_segmentation')}}), flush=True)
        selected = select_stage(stages)
        training = write_new(folder / 'training.json', {'manifest': training_manifest, 'optimizer_updates': 400,
            'losses': losses, 'batch_receipts': batches, 'trainable_parameters': sorted(SCOPE_PARAMETERS),
            'initial_complete_model_state_sha256': initial_full_state_sha, 'initial_optimizer_state_empty': True,
            'optimizer_resumed': False, 'trial_wall_limit_seconds': 900,
            'non_scope_state_sha256_before': initial_sha, 'non_scope_state_sha256_after': assert_frozen_state(loaded['parent']['model_state'], checkpoint['model_state']),
            'optimizer_trajectory_independently_replayed': False, 'wall_seconds': time.monotonic() - started})
        trials.append({'name': arm, 'arm': arm, 'seed': SEED, 'parent': loaded['config']['boundary_parent'],
                       'training': training, 'stages': stages, 'executed_steps': 400,
                       'selection': 'candidate' if selected else 'parent_fallback_no_eligible_scope_stage',
                       'selected_steps': selected['steps'] if selected else 0,
                       'checkpoint': selected['checkpoint'] if selected else loaded['config']['boundary_parent']})
    selections = write_new(output / 'selections-frozen.json', {'schema': SCHEMA, 'plan': plan, 'parent_tuning': parent_tuning,
        'trials': trials, 'executed_optimizer_updates': 800, 'all_training_and_selection_complete': True,
        'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False})
    heads = [{'name': 'parent', 'arm': 'parent', 'checkpoint': loaded['config']['boundary_parent'], 'selected_steps': 0,
              'selection': 'unchanged_parent_control'}, *[{k: t[k] for k in ('name', 'arm', 'checkpoint', 'selected_steps', 'selection')} for t in trials]]
    heads_ref = write_new(output / 'heads-frozen.json', heads)
    files, all_parent_generation = {}, None
    for head in heads:
        generation = decode(read_ref(head['checkpoint']), loaded['sources'])
        if head['name'] == 'parent': all_parent_generation = generation
        files[head['name']] = {}
        for panel, result in generation.items():
            assert_raw_token_identity(result, all_parent_generation[panel])
            files[head['name']][panel] = write_new(output / f"{head['name']}-{panel}-generation.json", result)
    frozen = {'schema': SCHEMA, 'plan': plan, 'selections': selections, 'heads': heads_ref, 'models': heads, 'files': files,
              'sources': {name: write_new(output / f'{name}-sources.json', rows) for name, rows in loaded['sources'].items()},
              'all_training_selection_and_generation_complete': True, 'executed_optimizer_updates': 800,
              'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False,
              'all_source_raw_token_logits_unchanged': True,
              'scope_profile_expanded': False, 'source_semantics_verified': False, 'production_promotion_performed': False}
    return write_new(output / 'generation-frozen.json', frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); print(json.dumps(run(args.config, args.output), sort_keys=True))
