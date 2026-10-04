#!/usr/bin/env python3
"""Matched residual boundary training with editorial punctuation rehearsal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_scope_retention_experiment as previous
from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as clause_runner
from scripts.ops.legal_ir import prepare_legal_heading_boundary_corpus as corpus
from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime

boundary, clauses, old = previous.boundary, previous.clauses, previous.old
require, digest, read_ref = previous.require, previous.digest, previous.read_ref
file_ref, write_new, sha = previous.file_ref, previous.write_new, previous.sha
SCHEMA = 'legal-heading-boundary-experiment/v1'
CONFIG_SCHEMA = 'legal-heading-boundary-config/v1'
ARMS, STEPS, SEED = ('control', 'rehearsal'), (100, 200, 400), 1730
TRAINABLE_COUNTS = {'control': 1057, 'rehearsal': 1057}
PARENT_SHA = previous.PARENT_SHA
CLAUSE_PARENTS = {
    'continuation': ('facet_retention', '8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
    'grounding': ('temporal_presence', '4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea'),
}
DOCUMENT_PANELS = ('heading_fresh', 'prior_preservation_fresh', 'root_condition_fresh_documents')
FALSE = {'source_semantics_verified': False, 'production_promotion_performed': False,
         'actual_latent_conditioning_validated': False, 'scope_profile_expanded': False,
         'all_logic_families_supported': False, 'qualified': False}


def read_config(path):
    config = json.loads(Path(path).read_bytes())
    require(type(config) is dict and set(config) == {'schema', 'heading_corpus_manifest',
        'boundary_parent', 'prior_generation', 'study_design', 'producer_files', 'clause_models'}
        and config['schema'] == CONFIG_SCHEMA, 'closed heading boundary config required')
    for key in ('heading_corpus_manifest', 'boundary_parent', 'prior_generation', 'study_design'):
        read_ref(config[key], parse=False)
    for reference in config['producer_files']: read_ref(reference, parse=False)
    require(config['boundary_parent']['sha256'] == PARENT_SHA, 'exact expanded1730 parent required')
    parent = read_ref(config['boundary_parent']); boundary.restore(parent)
    prior = read_ref(config['prior_generation'])
    require(prior['all_training_selection_and_generation_complete'] is True,
            'completed prior generation required')
    require(any(m['checkpoint']['sha256'] == PARENT_SHA for m in prior['models']),
            'parent absent from prior generation')
    models = config['clause_models']
    require(type(models) is list and len(models) == 2 and
            {m['architecture'] for m in models} == set(CLAUSE_PARENTS), 'two fixed clause parents required')
    for model in models:
        require(set(model) == {'name', 'architecture', 'decoder_kind', 'checkpoint'}, 'closed fixed clause descriptor required')
        kind, pin = CLAUSE_PARENTS[model['architecture']]
        require(model['name'] == 'parent_' + model['architecture'] and
                model['decoder_kind'] == kind and model['checkpoint']['sha256'] == pin,
                'fixed existing clause checkpoint required')
        read_ref(model['checkpoint'], parse=False)
    loaded = corpus.load_training_inputs(config['heading_corpus_manifest']['path'])
    tuning = dict(loaded['tuning'])
    sources = {name: clauses.source_rows(rows) for name, rows in tuning.items()}
    sources['heading_fresh'] = loaded['fresh_sources']
    replay = [r for rows in loaded['replay'].values() for r in rows]
    all_train = replay + loaded['new_train']
    require(len(replay) == len({r['source_sha256'] for r in replay}) == 768,
            'all768 historical replay rows required')
    require(len(loaded['new_train']) == 384 and len(all_train) == len({r['source_sha256'] for r in all_train}) == 1152,
            'same1152 distinct training inventory required')
    require(loaded['supported_replay'] == [r for r in replay if r['supported']] and len(loaded['supported_replay']) == 528,
            'exact528 supported historical rows required')
    require(loaded['supported_heading'] == [r for r in loaded['new_train'] if r['supported']] and len(loaded['supported_heading']) == 192,
            'exact192 supported heading rows required')
    require(loaded['boundary_training'] == loaded['supported_replay'] + loaded['supported_heading'],
            'exact720 supported-only fitting inventory required')
    fit_hashes = {r['source_sha256'] for r in all_train}
    for name, rows in sources.items():
        require(not fit_hashes & {r['source_sha256'] for r in rows}, 'fit/evaluation source overlap: ' + name)
    require(len(tuning) == 20 and sum(map(len, tuning.values())) == 2160,
            'all20 tuning panels and2160 rows required')
    require(len(sources) == 21 and sum(map(len, sources.values())) == 2352,
            'all21 source panels and2352 rows required')
    require(set(DOCUMENT_PANELS) <= set(sources), 'all planned document panels required')
    return {'config': config, 'manifest': loaded['manifest'], 'parent': parent,
            'replay': replay, 'new_train': loaded['new_train'],
            'supported_replay': loaded['supported_replay'], 'supported_heading': loaded['supported_heading'],
            'boundary_training': loaded['boundary_training'], 'training_token_roles': loaded['training_token_roles'],
            'tuning': tuning, 'sources': sources}


def batch_schedule(replay, headings, steps=400):
    require(type(steps) is int and 1 <= steps <= 400, 'bounded matched update count required')
    require(replay and headings and all(r['supported'] is True for r in replay + headings),
            'supported-only endpoint supervision required')
    require(len({r['candidate_id'] for r in replay + headings}) == len(replay + headings),
            'distinct training identities required')
    common = old.CyclingRows(replay, random.Random(SEED))
    focused = old.CyclingRows(headings, random.Random(SEED + 1))
    for step in range(1, steps + 1):
        left, right = common.take(6), focused.take(6)
        yield left + right, {'steps': step, 'common_replay_ids': [r['candidate_id'] for r in left],
            'extra_ids': [r['candidate_id'] for r in right], 'supported_count': 12, 'unsupported_count': 0}


metrics = previous.metrics


def assert_raw_scope_identity(generation, parent_generation):
    require(len(generation['rows']) == len(parent_generation['rows']), 'scope preservation denominator differs')
    for row, parent in zip(generation['rows'], parent_generation['rows']):
        require(row['candidate_id'] == parent['candidate_id'] and row['source_sha256'] == parent['source_sha256'],
                'scope preservation source join differs')
        require(all(row[k] == parent[k] for k in ('scope_logits', 'scope_supported_probability', 'raw_learned_scope_supported')),
                'raw scope logits or decisions changed')
    return True


def validate_metrics(score):
    keys = ('documents', 'supported_documents', 'unsupported_documents', 'raw_boundary_document_exact',
            'raw_supported_scope_correct', 'exact_supported_segmentation', 'raw_unsupported_accepted', 'unsupported_accepted')
    require(all(type(score.get(k)) is int and score[k] >= 0 for k in keys), 'complete nonnegative integer boundary metrics required')
    require(score['documents'] == score['supported_documents'] + score['unsupported_documents'], 'boundary denominators differ')
    require(all(score[k] <= score['supported_documents'] for k in ('raw_supported_scope_correct', 'exact_supported_segmentation', 'raw_boundary_document_exact'))
            and all(score[k] <= score['unsupported_documents'] for k in ('raw_unsupported_accepted', 'unsupported_accepted')),
            'boundary successes exceed class denominators')


def gates(scores, parents, raw_scope_logits_unchanged):
    require(set(scores) == set(parents) and 'heading_new' in scores, 'complete preregistered tuning panel set required')
    failures = []
    if raw_scope_logits_unchanged is not True: failures.append('raw_scope_logits_changed')
    for panel in sorted(scores):
        score, parent = scores[panel], parents[panel]
        validate_metrics(score); validate_metrics(parent)
        require(all(score[k] == parent[k] for k in ('documents', 'supported_documents', 'unsupported_documents')),
                'complete tuning denominators differ')
        for key in ('raw_supported_scope_correct', 'raw_unsupported_accepted'):
            if score[key] != parent[key]: failures.append(panel + ':' + key + '_changed')
        for key in ('raw_boundary_document_exact', 'exact_supported_segmentation'):
            if score[key] < parent[key]: failures.append(panel + ':' + key + '_regressed')
        if score['unsupported_accepted'] > parent['unsupported_accepted']:
            failures.append(panel + ':final_unsupported_accepted_increased')
    if scores['heading_new']['raw_boundary_document_exact'] <= parents['heading_new']['raw_boundary_document_exact']:
        failures.append('heading_new:no_strict_raw_boundary_improvement')
    return {'eligible': not failures, 'failures': failures}


def ranking(stage):
    new = stage['metrics']['heading_new']
    return (new['raw_boundary_document_exact'], new['exact_supported_segmentation'],
            sum(s['raw_boundary_document_exact'] for p, s in stage['metrics'].items() if p != 'heading_new'), -stage['steps'])


def select_stage(stages):
    require(type(stages) is list and [s['steps'] for s in stages] == list(STEPS), 'all400 planned updates and stages required')
    require(all(type(s['eligible']) is bool for s in stages), 'explicit stage eligibility required')
    eligible = [s for s in stages if s['eligible']]
    return max(eligible, key=ranking) if eligible else None


def select_primary(trials):
    require(len(trials) == 2 and {t['name'] for t in trials} == set(ARMS), 'both heading boundary trials required')
    candidates = []
    for trial in trials:
        stage = select_stage(trial['stages'])
        require(trial['selected_steps'] == (stage['steps'] if stage else 0), 'trial selection differs from declared stage rank')
        if stage is not None: candidates.append((trial, stage))
    return max(candidates, key=lambda x: (*ranking(x[1]), -ARMS.index(x[0]['name'])))[0]['name'] if candidates else 'parent'


def decode(checkpoint, sources):
    decoder = runtime.decoder(checkpoint)
    return {name: clauses.decode_all(decoder, rows) for name, rows in sources.items()}


def run(config_path, output):
    import torch
    torch.set_num_threads(1)
    loaded = read_config(config_path)
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    modules = (corpus, previous, old, boundary, clauses, clauses.compose, runtime, clause_runner, sys.modules[__name__])
    pins = {str(Path(m.__file__).resolve()): sha(Path(m.__file__).read_bytes()) for m in modules}
    plan = write_new(output / 'plan.json', {
        'schema': SCHEMA, 'config': file_ref(config_path), 'producer_pins': pins,
        'arms': list(ARMS), 'seed': SEED, 'stages': list(STEPS), 'steps_per_arm': 400,
        'trainable_parameter_counts': TRAINABLE_COUNTS,
        'learning_rate': .004, 'positive_token_weight': 12., 'optimizer': 'fresh_Adam',
        'editorial_rehearsal_weight_by_arm': {'control': 0., 'rehearsal': .5},
        'auxiliary': 'Half mean BCE over true endpoints plus half mean BCE over annotated editorial punctuation negatives.',
        'base_loss': 'BCE(pos_weight12) mean over supported valid tokens; unsupported rows have no boundary supervision.',
        'gradient_clip_norm': 5., 'trial_wall_limit_seconds': 1200,
        'trial_wall_limit_scope': 'optimization_and_stage_evaluation_excludes_initial_parity_setup',
        'identical_batches_all_arms': True, 'common_supported_replay_rows': 6, 'supported_heading_rows_per_batch': 6,
        'scope_threshold_and_surface_policy_unchanged': True, 'clause_predictions_used_for_selection': False,
        'new_fresh_targets_opened': False, 'tuning_counts': {k: len(v) for k, v in loaded['tuning'].items()},
        'source_counts': {k: len(v) for k, v in loaded['sources'].items()},
        'training_inventory_count': 1152, 'supported_training_count': 720, 'unsupported_excluded_from_fitting': 432,
        'new_training_count': 0, 'supported_replay_count': 528, 'supported_heading_count': 192,
        'full_training_diagnostic_slots': ['parent', *[a + '_final400' for a in ARMS]],
        'postselection_challenge_diagnostic_slots': [a + '_final400' for a in ARMS],
        'challenge_diagnostics_used_for_selection': False,
        'training_fit_diagnostics_used_for_selection': False,
        'training_source_inventory_sha256': digest(loaded['replay'] + loaded['new_train']),
        'training_token_roles_sha256': digest(loaded['training_token_roles']),
        'document_panels': list(DOCUMENT_PANELS), 'clause_models': loaded['config']['clause_models'],
        'component_eligibility_is_not_deployment_qualification': True,
        'scope': 'One-seed matched residual token-boundary loss comparison; fixed encoder, base readout, scope and clause decoders.', **FALSE})
    tuning_sources = {name: loaded['sources'][name] for name in loaded['tuning']}
    parent_generation = decode(loaded['parent'], tuning_sources)
    parent_metrics = {name: metrics(parent_generation[name], rows) for name, rows in loaded['tuning'].items()}
    parent_tuning = write_new(output / 'parent-tuning.json', {'generation': parent_generation, 'metrics': parent_metrics})
    trials, initial_state_sha, batches_sha = [], None, None
    for arm in ARMS:
        folder = output / arm; folder.mkdir()
        manifest = {'arm': arm, 'seed': SEED, 'plan': plan, 'steps': 400,
                    'supported_replay_sha256': digest(loaded['supported_replay']),
                    'supported_heading_sha256': digest(loaded['supported_heading']),
                    'training_token_roles_sha256': digest(loaded['training_token_roles'])}
        initial = runtime.build_checkpoint(loaded['parent'], arm=arm, seed=SEED,
            training_manifest_sha256=digest(manifest), tuning_manifest_sha256=digest(loaded['tuning']),
            parent_file_sha256=loaded['config']['boundary_parent']['sha256'])
        initial_ref = write_new(folder / 'checkpoint-initial.json', initial)
        _, network = runtime.restore(initial)
        trainable = runtime.configure_trainable(network, arm)
        trainable_names = [n for n, p in network.named_parameters() if p.requires_grad]
        require(sum(p.numel() for p in trainable) == TRAINABLE_COUNTS[arm], 'trainable parameter budget differs')
        complete_state_sha = digest({k: v.tolist() for k, v in network.state_dict().items()})
        if initial_state_sha is None: initial_state_sha = complete_state_sha
        require(complete_state_sha == initial_state_sha, 'arms must start with identical full numerical state')
        init_generation = decode(initial, tuning_sources)
        require(all(init_generation[p]['rows'] == parent_generation[p]['rows'] for p in tuning_sources),
                'initial complete source predictions differ from parent')
        optimizer = torch.optim.Adam(trainable, lr=.004)
        require(not optimizer.state and not optimizer.state_dict()['state'], 'fresh empty Adam required')
        stages, losses, batches, loss_receipts = [], [], [], []
        started = time.monotonic()
        for rows, receipt in batch_schedule(loaded['supported_replay'], loaded['supported_heading']):
            step = receipt['steps']; network.train(); optimizer.zero_grad(set_to_none=True)
            ids, features, lengths, labels, scopes, valid = boundary.tensor_batch(torch, rows, labels=True)
            positive, negative = runtime.token_role_masks(torch, rows, loaded['training_token_roles'])
            logits, _ = network(ids, features, lengths)
            loss, parts = runtime.objective_loss(torch, logits, labels, valid, scopes.bool(), positive, negative, arm=arm)
            require(bool(torch.isfinite(loss)), 'finite heading boundary objective required')
            record = {'steps': step, 'candidate_logits': logits.detach().tolist(), 'labels': labels.tolist(),
                      'valid_mask': valid.tolist(), 'supported': scopes.bool().tolist(),
                      'positive_mask': positive.tolist(), 'negative_mask': negative.tolist(),
                      'objective_components': parts, 'total_loss': float(loss.detach())}
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(trainable, 5.)
            require(bool(torch.isfinite(norm)) and all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in trainable),
                    'finite boundary gradients required')
            optimizer.step()
            require(all(bool(torch.isfinite(p).all()) for p in trainable), 'finite updated parameters required')
            losses.append(float(loss.detach())); batches.append(receipt)
            loss_receipts.append({**record, 'gradient_norm_before_clipping': float(norm),
                                  'gradient_clip_norm': 5., 'finite_updated_parameters': True})
            require(time.monotonic() - started < 1200., 'bounded boundary trial wall budget exhausted')
            if step not in STEPS: continue
            checkpoint = runtime.checkpoint(network, initial_checkpoint=initial, additional_steps=step)
            state_sha = runtime.assert_frozen_state(loaded['parent']['model_state'], checkpoint['model_state'])
            checkpoint_ref = write_new(folder / f'checkpoint-{step}.json', checkpoint)
            generation = decode(checkpoint, tuning_sources)
            scope_identity = all(assert_raw_scope_identity(generation[p], parent_generation[p]) for p in generation)
            scores = {p: metrics(generation[p], rows) for p, rows in loaded['tuning'].items()}
            evaluated = write_new(folder / f'stage-{step}-tuning.json', {'generation': generation, 'metrics': scores})
            require(time.monotonic() - started < 1200., 'boundary trial wall budget exhausted during stage evaluation')
            stage = {'steps': step, 'checkpoint': checkpoint_ref, 'tuning': evaluated, 'metrics': scores,
                     'frozen_base_state_sha256': state_sha, 'raw_scope_logits_unchanged': scope_identity,
                     **gates(scores, parent_metrics, scope_identity)}
            stages.append(stage)
            print(json.dumps({'arm': arm, 'steps': step, 'eligible': stage['eligible'], 'failures': stage['failures'],
                'heading_new': {k: scores['heading_new'][k] for k in ('raw_boundary_document_exact', 'exact_supported_segmentation', 'unsupported_accepted')}}), flush=True)
        selected = select_stage(stages)
        if batches_sha is None: batches_sha = digest(batches)
        require(digest(batches) == batches_sha, 'arms must see identical per-step input identities')
        optimizer_steps = {n: int(optimizer.state[p]['step']) for n, p in network.named_parameters() if p.requires_grad}
        require(set(optimizer_steps.values()) == {400}, 'all trainable Adam parameters require400 updates')
        training = write_new(folder / 'training.json', {'manifest': manifest, 'optimizer_updates': 400,
            'losses': losses, 'loss_receipts': loss_receipts, 'batch_receipts': batches,
            'batch_receipts_sha256': batches_sha, 'trainable_parameters': trainable_names,
            'trainable_parameter_count': sum(p.numel() for p in trainable), 'optimizer_parameter_steps': optimizer_steps,
            'initial_complete_model_state_sha256': complete_state_sha, 'initial_predictions_equal_parent': True,
            'initial_optimizer_state_empty': True, 'optimizer_resumed': False,
            'optimizer_trajectory_independently_replayed': False, 'trial_wall_limit_seconds': 1200,
            'trial_wall_limit_scope': 'optimization_and_stage_evaluation_excludes_initial_parity_setup',
            'wall_seconds': time.monotonic() - started})
        trials.append({'name': arm, 'arm': arm, 'seed': SEED, 'parent': loaded['config']['boundary_parent'],
            'initial_checkpoint': initial_ref, 'training': training, 'stages': stages, 'executed_steps': 400,
            'selection': 'candidate' if selected else 'parent_fallback_no_eligible_boundary_stage',
            'selected_steps': selected['steps'] if selected else 0,
            'checkpoint': selected['checkpoint'] if selected else loaded['config']['boundary_parent']})
    primary = select_primary(trials)
    selections = write_new(output / 'selections-frozen.json', {'schema': SCHEMA, 'plan': plan, 'parent_tuning': parent_tuning,
        'trials': trials, 'executed_optimizer_updates': 800, 'all_training_and_selection_complete': True,
        'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False,
        'primary_boundary_choice': primary, 'choice_fixed_before_fresh_reference_release': True})
    training_diagnostics = {}
    training_panels = {'historical_replay': loaded['replay'], 'new_training': loaded['new_train']}
    diagnostic_models = [('parent', loaded['config']['boundary_parent'])] + [
        (t['name'] + '_final400', t['stages'][-1]['checkpoint']) for t in trials]
    training_parent = None
    for name, checkpoint_ref in diagnostic_models:
        generation = decode(read_ref(checkpoint_ref), {p: clauses.source_rows(rows) for p, rows in training_panels.items()})
        if training_parent is None: training_parent = generation
        for panel in generation: assert_raw_scope_identity(generation[panel], training_parent[panel])
        training_diagnostics[name] = write_new(output / f'{name}-training-diagnostic.json', {
            'checkpoint': checkpoint_ref, 'generation': generation,
            'metrics': {p: metrics(generation[p], rows) for p, rows in training_panels.items()},
            'training_fit_used_for_selection': False, 'heldout_accuracy': False})
    heads = [{'name': 'parent', 'arm': 'parent', 'checkpoint': loaded['config']['boundary_parent'], 'selected_steps': 0,
              'selection': 'unchanged_parent_control'}, *[{k: t[k] for k in ('name', 'arm', 'checkpoint', 'selected_steps', 'selection')} for t in trials]]
    heads = [{**head, 'diagnostic_only': False} for head in heads] + [
        {'name': t['name'] + '_final400', 'arm': t['arm'], 'checkpoint': t['stages'][-1]['checkpoint'],
         'selected_steps': 400, 'selection': 'postselection_final400_diagnostic', 'diagnostic_only': True}
        for t in trials]
    heads_ref = write_new(output / 'heads-frozen.json', heads)
    files, boundary_generations = {}, {}
    for head in heads:
        generation = decode(read_ref(head['checkpoint']), loaded['sources'])
        boundary_generations[head['name']] = generation
        files[head['name']] = {}
        for panel, result in generation.items():
            assert_raw_scope_identity(result, boundary_generations['parent'][panel])
            files[head['name']][panel] = write_new(output / f"{head['name']}-{panel}-generation.json", result)
    source_refs = {p: write_new(output / f'{p}-sources.json', rows) for p, rows in loaded['sources'].items()}
    pipelines, document_files = [], {}
    for model in loaded['config']['clause_models']:
        decoder = clause_runner.load_decoder(model['checkpoint'], model['decoder_kind'])
        for head in heads:
            name = model['name'] + '__boundary_' + head['name']
            pipelines.append({**model, 'name': name, 'source_model_name': model['name'], 'boundary_head': head['name'],
                'boundary_checkpoint': head['checkpoint'], 'boundary_selection': head['selection'],
                'boundary_selected_steps': head['selected_steps'], 'diagnostic_only': head['diagnostic_only'],
                'clause_training_executed': False})
            document_files[name] = {p: write_new(output / f'{name}-{p}-documents.json',
                clause_runner.retention.generate_documents(decoder, boundary_generations[head['name']][p], loaded['sources'][p]))
                for p in DOCUMENT_PANELS}
    require(all(sha(Path(p).read_bytes()) == h for p, h in pins.items()) and read_config(config_path) == loaded,
            'boundary producer or configured input drift')
    frozen = {'schema': SCHEMA, 'plan': plan, 'selections': selections, 'heads': heads_ref, 'models': heads,
        'files': files, 'sources': source_refs, 'clause_models': loaded['config']['clause_models'],
        'training_diagnostics': training_diagnostics,
        'pipelines': pipelines, 'document_files': document_files,
        'document_sources': {p: source_refs[p] for p in DOCUMENT_PANELS},
        'all_training_selection_and_generation_complete': True, 'executed_optimizer_updates': 800,
        'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False,
        'all_source_raw_scope_logits_unchanged': True, 'primary_boundary_choice': primary,
        'selected_boundary_slots': 3, 'diagnostic_boundary_slots': 2,
        'challenge_diagnostics_used_for_selection': False,
        'choice_fixed_before_fresh_reference_release': True, 'no_joint_stage_search': True, **FALSE}
    return write_new(output / 'generation-frozen.json', frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); print(json.dumps(run(args.config, args.output), sort_keys=True))
