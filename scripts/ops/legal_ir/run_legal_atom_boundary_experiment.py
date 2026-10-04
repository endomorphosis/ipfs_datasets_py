#!/usr/bin/env python3
"""Matched warm continuation, interior-atom rehearsal and original-parent preservation."""
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
from scripts.ops.legal_ir import prepare_legal_atom_boundary_corpus as corpus
from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime

boundary, clauses, old = previous.boundary, previous.clauses, previous.old
require, digest, read_ref = previous.require, previous.digest, previous.read_ref
file_ref, write_new, sha = previous.file_ref, previous.write_new, previous.sha
SCHEMA = 'legal-atom-boundary-experiment/v1'
CONFIG_SCHEMA = 'legal-atom-boundary-config/v1'
ARMS, STEPS, SEED = ('continuation', 'atom_rehearsal', 'distill'), (100, 200, 400), 1730
TRAINABLE_COUNTS = {arm: 1057 for arm in ARMS}
PARENT_SHA = previous.PARENT_SHA
WARM_SHA = '63879904bdce7edb2717ca9a2d1a05569b5c2c6332d27bfcb250b9ed64ae3fba'
CLAUSE_PARENTS = {
    'continuation': ('facet_retention', '8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
    'grounding': ('temporal_presence', '4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea'),
}
DOCUMENT_PANELS = ('atom_fresh', 'prior_heading_fresh', 'root_condition_fresh_documents')
FALSE = {'source_semantics_verified': False, 'production_promotion_performed': False,
         'actual_latent_conditioning_validated': False, 'scope_profile_expanded': False,
         'all_logic_families_supported': False, 'qualified': False}


def read_config(path):
    config = json.loads(Path(path).read_bytes())
    require(type(config) is dict and set(config) == {'schema', 'atom_corpus_manifest',
        'boundary_parent', 'warm_start', 'prior_generation', 'study_design', 'producer_files', 'clause_models'}
        and config['schema'] == CONFIG_SCHEMA, 'closed heading boundary config required')
    for key in ('atom_corpus_manifest', 'boundary_parent', 'warm_start', 'prior_generation', 'study_design'):
        read_ref(config[key], parse=False)
    for reference in config['producer_files']: read_ref(reference, parse=False)
    require(config['boundary_parent']['sha256'] == PARENT_SHA, 'exact expanded1730 parent required')
    parent = read_ref(config['boundary_parent']); boundary.restore(parent)
    require(config['warm_start']['sha256'] == WARM_SHA, 'exact heading rehearsal400 warm start required')
    warm = read_ref(config['warm_start']); runtime.heading.restore(warm)
    require(warm['parent_checkpoint'] == parent and warm['optimizer_steps'] == 1200, 'warm and original parent lineage differs')
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
    loaded = corpus.load_training_inputs(config['atom_corpus_manifest']['path'])
    tuning = dict(loaded['tuning'])
    sources = {name: clauses.source_rows(rows) for name, rows in tuning.items()}
    sources['atom_fresh'] = loaded['fresh_sources']
    replay = [r for rows in loaded['replay'].values() for r in rows]
    all_train = replay + loaded['new_train'] + loaded['atom_train']
    require(len(replay) == len({r['source_sha256'] for r in replay}) == 768,
            'all768 historical replay rows required')
    require(len(loaded['new_train']) == 384 and len(loaded['atom_train']) == 144 and len(all_train) == len({r['source_sha256'] for r in all_train}) == 1296,
            'exact1296 distinct training inventory required')
    require(loaded['supported_replay'] == [r for r in replay if r['supported']] and len(loaded['supported_replay']) == 528,
            'exact528 supported historical rows required')
    require(loaded['supported_heading'] == [r for r in loaded['new_train'] if r['supported']] and len(loaded['supported_heading']) == 192,
            'exact192 supported heading rows required')
    require(loaded['boundary_training'] == loaded['supported_replay'] + loaded['supported_heading'] + loaded['atom_train'],
            'exact864 supported-only fitting inventory required')
    fit_hashes = {r['source_sha256'] for r in all_train}
    for name, rows in sources.items():
        require(not fit_hashes & {r['source_sha256'] for r in rows}, 'fit/evaluation source overlap: ' + name)
    require(len(tuning) == 22 and sum(map(len, tuning.values())) == 2448,
            'all22 tuning panels and2448 rows required')
    require(len(sources) == 23 and sum(map(len, sources.values())) == 2640,
            'all23 source panels and2640 rows required')
    require(set(DOCUMENT_PANELS) <= set(sources), 'all planned document panels required')
    return {'config': config, 'manifest': loaded['manifest'], 'parent': parent, 'warm': warm,
            'replay': replay, 'new_train': loaded['new_train'],
            'atom_train': loaded['atom_train'], 'atom_training_pairs': loaded['atom_training_pairs'],
            'supported_replay': loaded['supported_replay'], 'supported_heading': loaded['supported_heading'],
            'boundary_training': loaded['boundary_training'], 'training_token_roles': loaded['training_token_roles'], 'training_atom_roles': loaded['training_atom_roles'],
            'tuning': tuning, 'sources': sources}


def batch_schedule(replay, headings, atoms, pairs, steps=400):
    require(type(steps) is int and 1 <= steps <= 400, 'bounded matched update count required')
    require(replay and headings and atoms and all(r['supported'] is True for r in replay + headings + atoms),
            'supported-only endpoint supervision required')
    require(len({r['candidate_id'] for r in replay + headings + atoms}) == len(replay + headings + atoms),
            'distinct training identities required')
    by_id = {r['candidate_id']: r for r in atoms}
    require(len(pairs) * 2 == len(atoms) and len({p['pair_id'] for p in pairs}) == len(pairs),
            'complete unique atom rotation pairs required')
    members = [p[key] for p in pairs for key in ('forward_id', 'rotated_id')]
    require(len(members) == len(set(members)) and set(members) == set(by_id), 'exact atom pair membership required')
    common = old.CyclingRows(replay, random.Random(SEED))
    focused = old.CyclingRows(headings, random.Random(SEED + 1))
    atom_pairs = old.CyclingRows(pairs, random.Random(SEED + 2))
    for step in range(1, steps + 1):
        left, middle, chosen = common.take(4), focused.take(4), atom_pairs.take(2)
        right = [by_id[p[key]] for p in chosen for key in ('forward_id', 'rotated_id')]
        yield left + middle + right, {'steps': step, 'common_replay_ids': [r['candidate_id'] for r in left],
            'heading_ids': [r['candidate_id'] for r in middle], 'atom_ids': [r['candidate_id'] for r in right],
            'atom_pair_ids': [p['pair_id'] for p in chosen], 'supported_count': 12, 'unsupported_count': 0}


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


def source_churn(generation, parent_generation, references):
    require(len(generation['rows']) == len(parent_generation['rows']) == len(references), 'complete source-churn denominator required')
    result = {k: [] for k in ('parent_unsupported_ids', 'candidate_unsupported_ids', 'new_unsupported_ids',
        'removed_unsupported_ids', 'supported_raw_wins', 'supported_raw_losses',
        'supported_delivered_wins', 'supported_delivered_losses')}
    for row, parent, target in zip(generation['rows'], parent_generation['rows'], references, strict=True):
        require(row['candidate_id'] == parent['candidate_id'] == target['candidate_id']
                and row['source_sha256'] == parent['source_sha256'] == target['source_sha256'], 'source-churn join differs')
        require(row['status'] in ('segmented', 'abstained') and parent['status'] in ('segmented', 'abstained'), 'known boundary decision required')
        identity = target['candidate_id']
        if not target['supported']:
            if parent['status'] == 'segmented': result['parent_unsupported_ids'].append(identity)
            if row['status'] == 'segmented': result['candidate_unsupported_ids'].append(identity)
            continue
        tokens = boundary.tokenize(target['source_text'])
        expected = {c['char_end'] for c in target['clauses']}
        wanted = [(c['char_start'], c['char_end']) for c in target['clauses']]
        correct = []
        for prediction in (parent, row):
            raw = {tokens[i]['char_end'] for i in prediction['boundary_token_indices']} == expected
            actual = [(c['char_start'], c['char_end']) for c in prediction['plan']['clauses']] if prediction['plan'] else []
            correct.append((raw, actual == wanted))
        for index, kind in enumerate(('raw', 'delivered')):
            if correct[1][index] and not correct[0][index]: result['supported_' + kind + '_wins'].append(identity)
            if correct[0][index] and not correct[1][index]: result['supported_' + kind + '_losses'].append(identity)
    result['new_unsupported_ids'] = sorted(set(result['candidate_unsupported_ids']) - set(result['parent_unsupported_ids']))
    result['removed_unsupported_ids'] = sorted(set(result['parent_unsupported_ids']) - set(result['candidate_unsupported_ids']))
    return {k: sorted(v) for k, v in result.items()}


def gates(scores, parents, raw_scope_logits_unchanged, churn):
    require(set(scores) == set(parents) == set(churn) and 'atom_new' in scores, 'complete preregistered tuning panel set required')
    failures = []
    if raw_scope_logits_unchanged is not True: failures.append('raw_scope_logits_changed')
    for panel in sorted(scores):
        score, parent = scores[panel], parents[panel]
        validate_metrics(score); validate_metrics(parent)
        changes = churn[panel]
        for key in ('parent_unsupported_ids', 'candidate_unsupported_ids', 'new_unsupported_ids', 'removed_unsupported_ids'):
            require(type(changes.get(key)) is list and all(type(v) is str for v in changes[key])
                    and changes[key] == sorted(set(changes[key])), 'complete sorted source churn identities required')
        old_ids, new_ids = set(changes['parent_unsupported_ids']), set(changes['candidate_unsupported_ids'])
        require(changes['new_unsupported_ids'] == sorted(new_ids - old_ids)
                and changes['removed_unsupported_ids'] == sorted(old_ids - new_ids)
                and len(old_ids) == parent['unsupported_accepted'] and len(new_ids) == score['unsupported_accepted'],
                'per-source and count acceptance metrics differ')
        if changes['new_unsupported_ids']: failures.append(panel + ':new_unsupported_sources_accepted')
        require(all(score[k] == parent[k] for k in ('documents', 'supported_documents', 'unsupported_documents')),
                'complete tuning denominators differ')
        for key in ('raw_supported_scope_correct', 'raw_unsupported_accepted'):
            if score[key] != parent[key]: failures.append(panel + ':' + key + '_changed')
        for key in ('raw_boundary_document_exact', 'exact_supported_segmentation'):
            if score[key] < parent[key]: failures.append(panel + ':' + key + '_regressed')
        if score['unsupported_accepted'] > parent['unsupported_accepted']:
            failures.append(panel + ':final_unsupported_accepted_increased')
    if scores['atom_new']['raw_boundary_document_exact'] <= parents['atom_new']['raw_boundary_document_exact']:
        failures.append('atom_new:no_strict_raw_boundary_improvement')
    return {'eligible': not failures, 'failures': failures}


def ranking(stage):
    new = stage['metrics']['atom_new']
    return (new['raw_boundary_document_exact'], new['exact_supported_segmentation'],
            sum(s['raw_boundary_document_exact'] for p, s in stage['metrics'].items() if p != 'atom_new'), -stage['steps'])


def select_stage(stages):
    require(type(stages) is list and [s['steps'] for s in stages] == list(STEPS), 'all400 planned updates and stages required')
    require(all(type(s['eligible']) is bool for s in stages), 'explicit stage eligibility required')
    eligible = [s for s in stages if s['eligible']]
    return max(eligible, key=ranking) if eligible else None


def select_primary(trials):
    require(len(trials) == 3 and {t['name'] for t in trials} == set(ARMS), 'all three atom boundary trials required')
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
    modules = (corpus, previous, old, boundary, clauses, clauses.compose, runtime, runtime.heading, clause_runner, sys.modules[__name__])
    pins = {str(Path(m.__file__).resolve()): sha(Path(m.__file__).read_bytes()) for m in modules}
    plan = write_new(output / 'plan.json', {
        'schema': SCHEMA, 'config': file_ref(config_path), 'producer_pins': pins,
        'arms': list(ARMS), 'seed': SEED, 'stages': list(STEPS), 'steps_per_arm': 400,
        'trainable_parameter_counts': TRAINABLE_COUNTS,
        'learning_rate': .004, 'positive_token_weight': 12., 'optimizer': 'fresh_Adam',
        'editorial_rehearsal_weight_by_arm': {a: .5 for a in ARMS},
        'atom_rehearsal_weight_by_arm': {'continuation': 0., 'atom_rehearsal': .5, 'distill': .5},
        'teacher_kl_weight_by_arm': {'continuation': 0., 'atom_rehearsal': 0., 'distill': .25},
        'teacher': loaded['config']['boundary_parent'], 'warm_start': loaded['config']['warm_start'],
        'teacher_mask': 'supported_valid_tokens_whose_original_teacher_threshold_matches_gold',
        'teacher_class_average': 'available_gold_classes', 'teacher_kl_temperature': 1.,
        'atom_auxiliary': 'Half mean BCE over inter-clause true ends plus half mean BCE over all interior actor/temporal/exception tokens.',
        'auxiliary': 'Half mean BCE over true endpoints plus half mean BCE over annotated editorial punctuation negatives.',
        'base_loss': 'BCE(pos_weight12) mean over supported valid tokens; unsupported rows have no boundary supervision.',
        'gradient_clip_norm': 5., 'trial_wall_limit_seconds': 1200,
        'trial_wall_limit_scope': 'optimization_and_stage_evaluation_excludes_initial_parity_setup',
        'identical_batches_all_arms': True, 'common_supported_replay_rows': 4, 'supported_heading_rows_per_batch': 4,
        'atom_pairs_per_batch': 2, 'supported_atom_rows_per_batch': 4,
        'scope_threshold_and_surface_policy_unchanged': True, 'clause_predictions_used_for_selection': False,
        'new_fresh_targets_opened': False, 'tuning_counts': {k: len(v) for k, v in loaded['tuning'].items()},
        'source_counts': {k: len(v) for k, v in loaded['sources'].items()},
        'training_inventory_count': 1296, 'supported_training_count': 864, 'unsupported_excluded_from_fitting': 432,
        'new_training_count': 144, 'supported_replay_count': 528, 'supported_heading_count': 192, 'supported_atom_count': 144,
        'full_training_diagnostic_slots': ['parent', 'warm_start', *[a + '_final400' for a in ARMS]],
        'postselection_challenge_diagnostic_slots': ['warm_start', *[a + '_final400' for a in ARMS]],
        'challenge_diagnostics_used_for_selection': False,
        'training_fit_diagnostics_used_for_selection': False,
        'training_source_inventory_sha256': digest(loaded['replay'] + loaded['new_train'] + loaded['atom_train']),
        'training_token_roles_sha256': digest(loaded['training_token_roles']),
        'training_atom_roles_sha256': digest(loaded['training_atom_roles']),
        'document_panels': list(DOCUMENT_PANELS), 'clause_models': loaded['config']['clause_models'],
        'component_eligibility_is_not_deployment_qualification': True,
        'scope': 'One-seed warm-start comparison of continuation, interior-atom rehearsal and correct-original-parent token distillation; fixed base and scope.',
        'per_source_unsupported_acceptance_subset_required': True, **FALSE})
    tuning_sources = {name: loaded['sources'][name] for name in loaded['tuning']}
    parent_generation = decode(loaded['parent'], tuning_sources)
    parent_metrics = {name: metrics(parent_generation[name], rows) for name, rows in loaded['tuning'].items()}
    parent_tuning = write_new(output / 'parent-tuning.json', {'generation': parent_generation, 'metrics': parent_metrics})
    warm_generation = decode(loaded['warm'], tuning_sources)
    require(all(assert_raw_scope_identity(warm_generation[p], parent_generation[p]) for p in tuning_sources), 'warm scope changed')
    warm_tuning = write_new(output / 'warm-start-tuning.json', {'generation': warm_generation,
        'metrics': {p: metrics(warm_generation[p], rows) for p, rows in loaded['tuning'].items()}})
    _, teacher = boundary.restore(loaded['parent'])
    teacher.eval()
    for parameter in teacher.parameters(): parameter.requires_grad_(False)
    teacher_state_sha = digest({k: v.tolist() for k, v in teacher.state_dict().items()})
    require(teacher_state_sha == digest(loaded['parent']['model_state']), 'exact original teacher required')
    trials, initial_state_sha, batches_sha, teacher_outputs_sha, teacher_masks_sha = [], None, None, None, None
    for arm in ARMS:
        folder = output / arm; folder.mkdir()
        manifest = {'arm': arm, 'seed': SEED, 'plan': plan, 'steps': 400,
                    'supported_replay_sha256': digest(loaded['supported_replay']),
                    'supported_heading_sha256': digest(loaded['supported_heading']),
                    'training_token_roles_sha256': digest(loaded['training_token_roles']),
                    'training_atom_roles_sha256': digest(loaded['training_atom_roles']),
                    'atom_training_sha256': digest(loaded['atom_train']),
                    'atom_training_pairs_sha256': digest(loaded['atom_training_pairs'])}
        initial = runtime.build_checkpoint(loaded['warm'], arm=arm, seed=SEED,
            training_manifest_sha256=digest(manifest), tuning_manifest_sha256=digest(loaded['tuning']),
            parent_file_sha256=loaded['config']['warm_start']['sha256'])
        initial_ref = write_new(folder / 'checkpoint-initial.json', initial)
        _, network = runtime.restore(initial)
        trainable = runtime.configure_trainable(network, arm)
        trainable_names = [n for n, p in network.named_parameters() if p.requires_grad]
        require(sum(p.numel() for p in trainable) == TRAINABLE_COUNTS[arm], 'trainable parameter budget differs')
        complete_state_sha = digest({k: v.tolist() for k, v in network.state_dict().items()})
        if initial_state_sha is None: initial_state_sha = complete_state_sha
        require(complete_state_sha == initial_state_sha, 'arms must start with identical full numerical state')
        init_generation = decode(initial, tuning_sources)
        require(all(init_generation[p]['rows'] == warm_generation[p]['rows'] for p in tuning_sources),
                'initial complete source predictions differ from warm start')
        optimizer = torch.optim.Adam(trainable, lr=.004)
        require(not optimizer.state and not optimizer.state_dict()['state'], 'fresh empty Adam required')
        stages, losses, batches, loss_receipts = [], [], [], []
        started = time.monotonic()
        for rows, receipt in batch_schedule(loaded['supported_replay'], loaded['supported_heading'], loaded['atom_train'], loaded['atom_training_pairs']):
            step = receipt['steps']; network.train(); optimizer.zero_grad(set_to_none=True)
            ids, features, lengths, labels, scopes, valid = boundary.tensor_batch(torch, rows, labels=True)
            positive, negative = runtime.token_role_masks(torch, rows, loaded['training_token_roles'])
            transition, atom_mask = runtime.atom_role_masks(torch, rows, loaded['training_atom_roles'])
            with torch.no_grad(): teacher_logits, _ = teacher(ids, features, lengths)
            logits, _ = network(ids, features, lengths)
            loss, parts = runtime.objective_loss(torch, logits, labels, valid, scopes.bool(), positive, negative,
                transition, atom_mask, teacher_logits=teacher_logits, arm=arm)
            require(bool(torch.isfinite(loss)), 'finite atom boundary objective required')
            record = {'steps': step, 'candidate_logits': logits.detach().tolist(), 'labels': labels.tolist(),
                      'valid_mask': valid.tolist(), 'supported': scopes.bool().tolist(),
                      'positive_mask': positive.tolist(), 'negative_mask': negative.tolist(),
                      'transition_mask': transition.tolist(), 'atom_mask': atom_mask.tolist(),
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
            churn = {p: source_churn(generation[p], parent_generation[p], rows) for p, rows in loaded['tuning'].items()}
            evaluated = write_new(folder / f'stage-{step}-tuning.json', {'generation': generation, 'metrics': scores, 'source_churn': churn})
            require(time.monotonic() - started < 1200., 'boundary trial wall budget exhausted during stage evaluation')
            stage = {'steps': step, 'checkpoint': checkpoint_ref, 'tuning': evaluated, 'metrics': scores,
                     'frozen_base_state_sha256': state_sha, 'raw_scope_logits_unchanged': scope_identity,
                     'source_churn': churn, **gates(scores, parent_metrics, scope_identity, churn)}
            stages.append(stage)
            print(json.dumps({'arm': arm, 'steps': step, 'eligible': stage['eligible'], 'failures': stage['failures'],
                'atom_new': {k: scores['atom_new'][k] for k in ('raw_boundary_document_exact', 'exact_supported_segmentation', 'unsupported_accepted')}}), flush=True)
        selected = select_stage(stages)
        if batches_sha is None: batches_sha = digest(batches)
        require(digest(batches) == batches_sha, 'arms must see identical per-step input identities')
        output_hash = digest([r['objective_components']['teacher_token_logits'] for r in loss_receipts])
        mask_hash = digest([r['objective_components']['teacher_correct_mask'] for r in loss_receipts])
        if teacher_outputs_sha is None: teacher_outputs_sha, teacher_masks_sha = output_hash, mask_hash
        require(output_hash == teacher_outputs_sha and mask_hash == teacher_masks_sha, 'identical original teacher outputs and masks required')
        require(digest({k: v.tolist() for k, v in teacher.state_dict().items()}) == teacher_state_sha
                and all(p.grad is None for p in teacher.parameters()), 'teacher changed or received gradients')
        optimizer_steps = {n: int(optimizer.state[p]['step']) for n, p in network.named_parameters() if p.requires_grad}
        require(set(optimizer_steps.values()) == {400}, 'all trainable Adam parameters require400 updates')
        training = write_new(folder / 'training.json', {'manifest': manifest, 'optimizer_updates': 400,
            'losses': losses, 'loss_receipts': loss_receipts, 'batch_receipts': batches,
            'batch_receipts_sha256': batches_sha, 'trainable_parameters': trainable_names,
            'trainable_parameter_count': sum(p.numel() for p in trainable), 'optimizer_parameter_steps': optimizer_steps,
            'initial_complete_model_state_sha256': complete_state_sha, 'initial_predictions_equal_warm_start': True,
            'teacher_outputs_sha256': teacher_outputs_sha, 'teacher_correct_masks_sha256': teacher_masks_sha,
            'teacher_state_sha256_before': teacher_state_sha, 'teacher_state_sha256_after': teacher_state_sha,
            'teacher_gradients_absent': True,
            'initial_optimizer_state_empty': True, 'optimizer_resumed': False,
            'optimizer_trajectory_independently_replayed': False, 'trial_wall_limit_seconds': 1200,
            'trial_wall_limit_scope': 'optimization_and_stage_evaluation_excludes_initial_parity_setup',
            'wall_seconds': time.monotonic() - started})
        trials.append({'name': arm, 'arm': arm, 'seed': SEED, 'parent': loaded['config']['boundary_parent'],
            'warm_start': loaded['config']['warm_start'],
            'initial_checkpoint': initial_ref, 'training': training, 'stages': stages, 'executed_steps': 400,
            'selection': 'candidate' if selected else 'parent_fallback_no_eligible_boundary_stage',
            'selected_steps': selected['steps'] if selected else 0,
            'checkpoint': selected['checkpoint'] if selected else loaded['config']['boundary_parent']})
    primary = select_primary(trials)
    selections = write_new(output / 'selections-frozen.json', {'schema': SCHEMA, 'plan': plan, 'parent_tuning': parent_tuning, 'warm_tuning': warm_tuning,
        'trials': trials, 'executed_optimizer_updates': 1200, 'all_training_and_selection_complete': True,
        'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False,
        'primary_boundary_choice': primary, 'choice_fixed_before_fresh_reference_release': True})
    training_diagnostics = {}
    training_panels = {'historical_replay': loaded['replay'], 'new_training': loaded['new_train'], 'atom_training': loaded['atom_train']}
    diagnostic_models = [('parent', loaded['config']['boundary_parent']), ('warm_start', loaded['config']['warm_start'])] + [
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
        {'name': 'warm_start', 'arm': 'warm_start', 'checkpoint': loaded['config']['warm_start'],
         'selected_steps': 0, 'selection': 'fixed_warm_start_diagnostic', 'diagnostic_only': True}] + [
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
        'all_training_selection_and_generation_complete': True, 'executed_optimizer_updates': 1200,
        'new_fresh_targets_opened': False, 'clause_predictions_used_for_selection': False,
        'all_source_raw_scope_logits_unchanged': True, 'primary_boundary_choice': primary,
        'selected_boundary_slots': 4, 'diagnostic_boundary_slots': 4,
        'challenge_diagnostics_used_for_selection': False,
        'choice_fixed_before_fresh_reference_release': True, 'no_joint_stage_search': True, **FALSE}
    return write_new(output / 'generation-frozen.json', frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); print(json.dumps(run(args.config, args.output), sort_keys=True))
