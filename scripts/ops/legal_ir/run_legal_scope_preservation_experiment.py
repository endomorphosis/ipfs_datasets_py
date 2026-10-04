#!/usr/bin/env python3
"""Matched readout freezing and teacher distillation with immutable boundaries."""
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
from scripts.ops.legal_ir import prepare_legal_scope_preservation_corpus as corpus
from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime

boundary, clauses, old = previous.boundary, previous.clauses, previous.old
require, digest, read_ref = previous.require, previous.digest, previous.read_ref
file_ref, write_new, sha = previous.file_ref, previous.write_new, previous.sha
SCHEMA = 'legal-scope-preservation-experiment/v1'
CONFIG_SCHEMA = 'legal-scope-preservation-config/v1'
ARMS, STEPS, SEED = ('control', 'freeze_readout', 'distill', 'freeze_distill'), (100, 200, 400), 1730
TRAINABLE_COUNTS = {'control': 1317, 'freeze_readout': 1187, 'distill': 1317, 'freeze_distill': 1187}
PARENT_SHA = previous.PARENT_SHA
CLAUSE_PARENTS = {
    'continuation': ('facet_retention', '8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
    'grounding': ('temporal_presence', '4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea'),
}
DOCUMENT_PANELS = ('scope_fresh', 'prior_adapter_fresh', 'root_condition_fresh_documents')
FALSE = {'source_semantics_verified': False, 'production_promotion_performed': False,
         'actual_latent_conditioning_validated': False, 'scope_profile_expanded': False,
         'all_logic_families_supported': False, 'qualified': False}


def read_config(path):
    config = json.loads(Path(path).read_bytes())
    require(type(config) is dict and set(config) == {'schema', 'scope_corpus_manifest',
        'boundary_parent', 'prior_scope_generation', 'additional_tuning_refs',
        'additional_source_refs', 'study_design', 'producer_files', 'clause_models'}
        and config['schema'] == CONFIG_SCHEMA, 'closed scope preservation config required')
    for key in ('scope_corpus_manifest', 'boundary_parent', 'prior_scope_generation', 'study_design'):
        read_ref(config[key], parse=False)
    for reference in config['producer_files']: read_ref(reference, parse=False)
    require(config['boundary_parent']['sha256'] == PARENT_SHA, 'exact expanded1730 parent required')
    parent = read_ref(config['boundary_parent']); boundary.restore(parent)
    prior = read_ref(config['prior_scope_generation'])
    require(prior['all_training_selection_and_generation_complete'] is True,
            'completed prior scope generation required')
    require(any(m['checkpoint']['sha256'] == PARENT_SHA for m in prior['models']),
            'parent absent from prior scope generation')
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
    loaded = corpus.load_training_inputs(config['scope_corpus_manifest']['path'])
    tuning = dict(loaded['tuning'])
    for name, reference in config['additional_tuning_refs'].items():
        require(name not in tuning, 'duplicate tuning panel name')
        rows = read_ref(reference)
        old.validate_references(rows, len(rows), sum(r['supported'] for r in rows))
        tuning[name] = rows
    sources = {name: clauses.source_rows(rows) for name, rows in tuning.items()}
    sources['scope_fresh'] = loaded['fresh_sources']
    for name, reference in config['additional_source_refs'].items():
        require(name not in sources, 'duplicate source panel name')
        rows = read_ref(reference); old.validate_sources(rows, len(rows)); sources[name] = rows
    replay = [r for rows in loaded['replay'].values() for r in rows]
    fit = replay + loaded['new_train']
    require(len(replay) == len({r['source_sha256'] for r in replay}) == 768,
            'all768 distinct historical replay rows required')
    require(len(loaded['new_train']) == 384 and len(fit) == len({r['source_sha256'] for r in fit}) == 1152,
            'all384 new disjoint training rows required')
    require(len(loaded['training_pairs']) == 192, 'all192 training contrast pairs required')
    fit_hashes = {r['source_sha256'] for r in fit}
    for name, rows in sources.items():
        require(not fit_hashes & {r['source_sha256'] for r in rows}, 'fit/evaluation source overlap: ' + name)
    require(set(DOCUMENT_PANELS) <= set(sources), 'all planned document panels required')
    return {'config': config, 'manifest': loaded['manifest'], 'parent': parent,
            'replay': replay, 'new_train': loaded['new_train'], 'training_pairs': loaded['training_pairs'],
            'tuning': tuning, 'sources': sources}


def batch_schedule(replay, new_train, pairs, steps=400):
    require(type(steps) is int and 1 <= steps <= 400, 'bounded matched update count required')
    common = old.CyclingRows(replay, random.Random(SEED))
    paired = old.CyclingRows(pairs, random.Random(SEED + 3))
    by_id = {r['candidate_id']: r for r in new_train}
    corpus.validate_pairs(new_train, pairs, len(pairs))
    for step in range(1, steps + 1):
        left, chosen = common.take(6), paired.take(3)
        right = [by_id[p[key]] for p in chosen for key in ('independent_id', 'nested_id')]
        require(sum(r['supported'] for r in right) == 3, 'balanced contrast batch required')
        rows = left + right
        yield rows, {'steps': step, 'common_replay_ids': [r['candidate_id'] for r in left],
                     'extra_ids': [r['candidate_id'] for r in right], 'pair_ids': [p['pair_id'] for p in chosen],
                     'supported_count': sum(r['supported'] for r in rows),
                     'unsupported_count': sum(not r['supported'] for r in rows)}


metrics = previous.metrics
assert_raw_token_identity = previous.assert_raw_token_identity


def validate_metrics(score):
    keys = ('documents', 'supported_documents', 'unsupported_documents',
            'raw_supported_scope_correct', 'exact_supported_segmentation',
            'raw_unsupported_accepted', 'unsupported_accepted')
    require(all(type(score.get(k)) is int and score[k] >= 0 for k in keys), 'complete nonnegative integer scope metrics required')
    require(score['documents'] == score['supported_documents'] + score['unsupported_documents'], 'scope denominators differ')
    require(all(score[k] <= score['supported_documents'] for k in ('raw_supported_scope_correct', 'exact_supported_segmentation'))
            and all(score[k] <= score['unsupported_documents'] for k in ('raw_unsupported_accepted', 'unsupported_accepted')),
            'scope successes exceed class denominators')


def gates(scores, parents, raw_token_logits_unchanged):
    require(set(scores) == set(parents) and 'scope_new' in scores, 'complete preregistered tuning panel set required')
    for panel in scores:
        validate_metrics(scores[panel]); validate_metrics(parents[panel])
    return previous.gates(scores, parents, raw_token_logits_unchanged)


def ranking(stage):
    new = stage['metrics']['scope_new']
    return (new['raw_supported_scope_correct'], new['exact_supported_segmentation'],
            sum(s['exact_supported_segmentation'] for p, s in stage['metrics'].items() if p != 'scope_new'), -stage['steps'])


def select_stage(stages):
    require(type(stages) is list and [s['steps'] for s in stages] == list(STEPS), 'all400 planned updates and stages required')
    require(all(type(s['eligible']) is bool for s in stages), 'explicit stage eligibility required')
    eligible = [s for s in stages if s['eligible']]
    return max(eligible, key=ranking) if eligible else None


def select_primary(trials):
    require(len(trials) == 4 and {t['name'] for t in trials} == set(ARMS), 'all four preservation trials required')
    candidates = []
    for trial in trials:
        stage = select_stage(trial['stages'])
        require(trial['selected_steps'] == (stage['steps'] if stage else 0), 'trial selection differs from declared stage rank')
        if stage is not None: candidates.append((trial, stage))
    return max(candidates, key=lambda x: (*ranking(x[1]), -ARMS.index(x[0]['name'])))[0]['name'] if candidates else 'parent'


def decode(checkpoint, sources):
    decoder = runtime.decoder(checkpoint)
    return {name: clauses.decode_all(decoder, rows) for name, rows in sources.items()}


def class_loss_receipt(torch, logits, scopes):
    losses = -torch.log_softmax(logits.detach(), dim=-1).gather(1, scopes[:, None]).squeeze(1)
    counts = [int((scopes == c).sum()) for c in (0, 1)]
    sums = [float(losses[scopes == c].sum()) for c in (0, 1)]
    return {'unsupported_count': counts[0], 'supported_count': counts[1],
            'unsupported_nll_sum': sums[0], 'supported_nll_sum': sums[1],
            'weighted_denominator': 3 * counts[0] + counts[1]}


def run(config_path, output):
    import torch
    torch.set_num_threads(1)
    loaded = read_config(config_path)
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    modules = (corpus, previous, old, boundary, clauses, clauses.compose, runtime, runtime.adapter, clause_runner, sys.modules[__name__])
    pins = {str(Path(m.__file__).resolve()): sha(Path(m.__file__).read_bytes()) for m in modules}
    plan = write_new(output / 'plan.json', {
        'schema': SCHEMA, 'config': file_ref(config_path), 'producer_pins': pins,
        'arms': list(ARMS), 'seed': SEED, 'stages': list(STEPS), 'steps_per_arm': 400,
        'trainable_parameter_counts': TRAINABLE_COUNTS,
        'learning_rate': .004, 'scope_class_weights': [3., 1.], 'optimizer': 'fresh_Adam',
        'distillation_weight_by_arm': {'control': 0., 'freeze_readout': 0., 'distill': 1., 'freeze_distill': 1.},
        'distillation_temperature': 1., 'teacher': loaded['config']['boundary_parent'],
        'teacher_mask': 'parent_raw_argmax_equals_training_scope_label',
        'distillation_reduction': 'mean_KL_parent_to_candidate_over_correct_teacher_rows_zero_if_empty',
        'all_arms_compute_identical_teacher_forwards_and_KL': True,
        'gradient_clip_norm': 5., 'trial_wall_limit_seconds': 1200,
        'trial_wall_limit_scope': 'optimization_and_stage_evaluation_excludes_initial_parity_setup',
        'identical_batches_all_arms': True, 'common_replay_rows': 6, 'contrast_pairs_per_batch': 3,
        'scope_threshold_and_surface_policy_unchanged': True, 'clause_predictions_used_for_selection': False,
        'new_fresh_targets_opened': False, 'tuning_counts': {k: len(v) for k, v in loaded['tuning'].items()},
        'source_counts': {k: len(v) for k, v in loaded['sources'].items()},
        'replay_count': 768, 'new_training_count': 384,
        'full_training_diagnostic_slots': ['parent', *[a + '_final400' for a in ARMS]],
        'training_fit_diagnostics_used_for_selection': False,
        'training_source_inventory_sha256': digest(loaded['replay'] + loaded['new_train']),
        'document_panels': list(DOCUMENT_PANELS), 'clause_models': loaded['config']['clause_models'],
        'scope': 'One-seed2x2 readout-freezing and correct-parent distillation comparison; fixed token boundaries and unchanged clause decoders.', **FALSE})
    tuning_sources = {name: loaded['sources'][name] for name in loaded['tuning']}
    parent_generation = decode(loaded['parent'], tuning_sources)
    parent_metrics = {name: metrics(parent_generation[name], rows) for name, rows in loaded['tuning'].items()}
    parent_tuning = write_new(output / 'parent-tuning.json', {'generation': parent_generation, 'metrics': parent_metrics})
    trials, initial_state_sha, batches_sha, teacher_receipts_sha = [], None, None, None
    _, teacher = boundary.restore(loaded['parent'])
    teacher.eval()
    for parameter in teacher.parameters(): parameter.requires_grad_(False)
    teacher_state_sha = digest({k: v.tolist() for k, v in teacher.state_dict().items()})
    require(teacher_state_sha == digest(loaded['parent']['model_state']), 'exact immutable teacher state required')
    for arm in ARMS:
        folder = output / arm; folder.mkdir()
        manifest = {'arm': arm, 'seed': SEED, 'plan': plan, 'steps': 400,
                    'replay_sha256': digest(loaded['replay']), 'new_training_sha256': digest(loaded['new_train']),
                    'training_pairs_sha256': digest(loaded['training_pairs'])}
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
        stages, losses, batches, loss_receipts, teacher_receipts = [], [], [], [], []
        started = time.monotonic()
        for rows, receipt in batch_schedule(loaded['replay'], loaded['new_train'], loaded['training_pairs']):
            step = receipt['steps']; network.train(); optimizer.zero_grad(set_to_none=True)
            ids, features, lengths, _, scopes, _ = boundary.tensor_batch(torch, rows, labels=True)
            with torch.no_grad(): _, teacher_logits = teacher(ids, features, lengths)
            _, logits = network(ids, features, lengths)
            loss, objective_parts = runtime.objective_loss(torch, logits, scopes, teacher_logits=teacher_logits, arm=arm)
            require(bool(torch.isfinite(loss)), 'finite scope preservation objective required')
            components = class_loss_receipt(torch, logits, scopes)
            candidate_values = logits.detach().tolist()
            teacher_record = {'steps': step, 'teacher_logits': teacher_logits.tolist(),
                              'teacher_correct_mask': (teacher_logits.argmax(-1) == scopes).tolist(),
                              'scope_labels': scopes.tolist()}
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(trainable, 5.)
            require(bool(torch.isfinite(norm)) and all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in trainable),
                    'finite scope gradients required')
            optimizer.step()
            require(all(bool(torch.isfinite(p).all()) for p in trainable), 'finite updated parameters required')
            losses.append(float(loss.detach())); batches.append(receipt)
            teacher_receipts.append(teacher_record)
            loss_receipts.append({'steps': step, **components, 'objective_components': objective_parts,
                'total_loss': losses[-1], 'candidate_logits': candidate_values,
                'gradient_norm_before_clipping': float(norm), 'gradient_clip_norm': 5., 'finite_updated_parameters': True})
            require(time.monotonic() - started < 1200., 'bounded scope trial wall budget exhausted')
            if step not in STEPS: continue
            checkpoint = runtime.checkpoint(network, initial_checkpoint=initial, additional_steps=step)
            state_sha = runtime.assert_frozen_state(loaded['parent']['model_state'], checkpoint['model_state'], arm=arm)
            checkpoint_ref = write_new(folder / f'checkpoint-{step}.json', checkpoint)
            generation = decode(checkpoint, tuning_sources)
            token_identity = all(assert_raw_token_identity(generation[p], parent_generation[p]) for p in generation)
            scores = {p: metrics(generation[p], rows) for p, rows in loaded['tuning'].items()}
            evaluated = write_new(folder / f'stage-{step}-tuning.json', {'generation': generation, 'metrics': scores})
            require(time.monotonic() - started < 1200., 'scope trial wall budget exhausted during stage evaluation')
            stage = {'steps': step, 'checkpoint': checkpoint_ref, 'tuning': evaluated, 'metrics': scores,
                     'frozen_non_scope_state_sha256': state_sha, 'raw_token_logits_unchanged': token_identity,
                     **gates(scores, parent_metrics, token_identity)}
            stages.append(stage)
            print(json.dumps({'arm': arm, 'steps': step, 'eligible': stage['eligible'], 'failures': stage['failures'],
                  'scope_new': {k: scores['scope_new'][k] for k in ('raw_supported_scope_correct', 'raw_unsupported_accepted', 'exact_supported_segmentation')}}), flush=True)
        selected = select_stage(stages)
        if batches_sha is None: batches_sha = digest(batches)
        require(digest(batches) == batches_sha, 'arms must see identical per-step input identities')
        if teacher_receipts_sha is None: teacher_receipts_sha = digest(teacher_receipts)
        require(digest(teacher_receipts) == teacher_receipts_sha, 'all arms must use identical frozen teacher outputs')
        require(teacher_state_sha == digest({k: v.tolist() for k, v in teacher.state_dict().items()})
                and all(p.grad is None for p in teacher.parameters()), 'teacher weights or gradients changed')
        optimizer_steps = {n: int(optimizer.state[p]['step']) for n, p in network.named_parameters() if p.requires_grad}
        require(set(optimizer_steps.values()) == {400}, 'all trainable Adam parameters require400 updates')
        training = write_new(folder / 'training.json', {'manifest': manifest, 'optimizer_updates': 400,
            'losses': losses, 'loss_receipts': loss_receipts, 'batch_receipts': batches,
            'teacher_receipts': teacher_receipts, 'teacher_receipts_sha256': teacher_receipts_sha,
            'teacher_state_sha256_before': teacher_state_sha, 'teacher_state_sha256_after': teacher_state_sha,
            'teacher_gradients_absent': True,
            'batch_receipts_sha256': batches_sha, 'trainable_parameters': trainable_names,
            'trainable_parameter_count': sum(p.numel() for p in trainable), 'optimizer_parameter_steps': optimizer_steps,
            'initial_complete_model_state_sha256': complete_state_sha, 'initial_predictions_equal_parent': True,
            'initial_optimizer_state_empty': True, 'optimizer_resumed': False,
            'optimizer_trajectory_independently_replayed': False, 'trial_wall_limit_seconds': 1200,
            'trial_wall_limit_scope': 'optimization_and_stage_evaluation_excludes_initial_parity_setup',
            'wall_seconds': time.monotonic() - started})
        trials.append({'name': arm, 'arm': arm, 'seed': SEED, 'parent': loaded['config']['boundary_parent'],
            'initial_checkpoint': initial_ref, 'training': training, 'stages': stages, 'executed_steps': 400,
            'selection': 'candidate' if selected else 'parent_fallback_no_eligible_scope_stage',
            'selected_steps': selected['steps'] if selected else 0,
            'checkpoint': selected['checkpoint'] if selected else loaded['config']['boundary_parent']})
    primary = select_primary(trials)
    selections = write_new(output / 'selections-frozen.json', {'schema': SCHEMA, 'plan': plan, 'parent_tuning': parent_tuning,
        'trials': trials, 'executed_optimizer_updates': 1600, 'all_training_and_selection_complete': True,
        'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False,
        'primary_scope_choice': primary, 'choice_fixed_before_fresh_reference_release': True})
    training_diagnostics = {}
    training_panels = {'historical_replay': loaded['replay'], 'new_training': loaded['new_train']}
    diagnostic_models = [('parent', loaded['config']['boundary_parent'])] + [
        (t['name'] + '_final400', t['stages'][-1]['checkpoint']) for t in trials]
    training_parent = None
    for name, checkpoint_ref in diagnostic_models:
        generation = decode(read_ref(checkpoint_ref), {p: clauses.source_rows(rows) for p, rows in training_panels.items()})
        if training_parent is None: training_parent = generation
        for panel in generation: assert_raw_token_identity(generation[panel], training_parent[panel])
        training_diagnostics[name] = write_new(output / f'{name}-training-diagnostic.json', {
            'checkpoint': checkpoint_ref, 'generation': generation,
            'metrics': {p: metrics(generation[p], rows) for p, rows in training_panels.items()},
            'training_fit_used_for_selection': False, 'heldout_accuracy': False})
    heads = [{'name': 'parent', 'arm': 'parent', 'checkpoint': loaded['config']['boundary_parent'], 'selected_steps': 0,
              'selection': 'unchanged_parent_control'}, *[{k: t[k] for k in ('name', 'arm', 'checkpoint', 'selected_steps', 'selection')} for t in trials]]
    heads_ref = write_new(output / 'heads-frozen.json', heads)
    files, boundary_generations = {}, {}
    for head in heads:
        generation = decode(read_ref(head['checkpoint']), loaded['sources'])
        boundary_generations[head['name']] = generation
        files[head['name']] = {}
        for panel, result in generation.items():
            assert_raw_token_identity(result, boundary_generations['parent'][panel])
            files[head['name']][panel] = write_new(output / f"{head['name']}-{panel}-generation.json", result)
    source_refs = {p: write_new(output / f'{p}-sources.json', rows) for p, rows in loaded['sources'].items()}
    pipelines, document_files = [], {}
    for model in loaded['config']['clause_models']:
        decoder = clause_runner.load_decoder(model['checkpoint'], model['decoder_kind'])
        for head in heads:
            name = model['name'] + '__scope_' + head['name']
            pipelines.append({**model, 'name': name, 'source_model_name': model['name'], 'boundary_head': head['name'],
                'boundary_checkpoint': head['checkpoint'], 'boundary_selection': head['selection'],
                'boundary_selected_steps': head['selected_steps'], 'clause_training_executed': False})
            document_files[name] = {p: write_new(output / f'{name}-{p}-documents.json',
                clause_runner.retention.generate_documents(decoder, boundary_generations[head['name']][p], loaded['sources'][p]))
                for p in DOCUMENT_PANELS}
    require(all(sha(Path(p).read_bytes()) == h for p, h in pins.items()) and read_config(config_path) == loaded,
            'scope producer or configured input drift')
    frozen = {'schema': SCHEMA, 'plan': plan, 'selections': selections, 'heads': heads_ref, 'models': heads,
        'files': files, 'sources': source_refs, 'clause_models': loaded['config']['clause_models'],
        'training_diagnostics': training_diagnostics,
        'pipelines': pipelines, 'document_files': document_files,
        'document_sources': {p: source_refs[p] for p in DOCUMENT_PANELS},
        'all_training_selection_and_generation_complete': True, 'executed_optimizer_updates': 1600,
        'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False,
        'all_source_raw_token_logits_unchanged': True, 'primary_scope_choice': primary,
        'choice_fixed_before_fresh_reference_release': True, 'no_joint_stage_search': True, **FALSE}
    return write_new(output / 'generation-frozen.json', frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); print(json.dumps(run(args.config, args.output), sort_keys=True))
