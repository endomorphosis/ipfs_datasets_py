#!/usr/bin/env python3
"""Independent selected-model qualification for balanced old/new replay.

Reconstructs initial/checkpoint/data/batch contracts and numerical inference.
Does not replay optimizer trajectories or grant general logic-family authority.
Fresh challenge labels remain unopened until all source-only replay and builds
freeze. Earlier192 and exposed150 panels are explicitly regression evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import math
import multiprocessing
import random
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_grounding_experiment as previous
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary
from scripts.ops.legal_ir import summarize_legal_native_conditioning_experiment as source_audit
from scripts.ops.legal_ir.summarize_legal_open_vocabulary_experiment import build_accounting

require, digest, read_ref, ref, write, sha = previous.require, previous.digest, previous.read_ref, previous.ref, previous.write, previous.sha
SCHEMA = 'legal-mixed-replay-independent-qualification/v1'
SEEDS = (1729, 1730, 1731)
ARMS = {'mixed_continuation': False, 'mixed_grounding': True}
PANEL_COUNTS = {'tuning_earlier': 96, 'tuning_new': 96, 'fresh': 144,
                'earlier_regression': 192, 'exposed_regression': 150}
FALSE = {'qualified': False, 'admitted': False, 'production_ready': False,
         'semantic_correctness_verified': False, 'all_logic_families_supported': False,
         'statutory_gold_available': False, 'optimizer_trajectory_replayed': False}


def retention_choice(stages, parent_exact, *, tolerance=1):
    """Independent policy on normalized tuning records; no challenge metrics."""
    require(type(parent_exact) is int and 0 <= parent_exact <= 96 and type(tolerance) is int and tolerance == 1,
            'bounded predeclared retention tolerance required')
    require(type(stages) is list and len(stages) == 2 and [r['steps'] for r in stages] == [400, 800],
            'both fixed training stages required')
    for row in stages:
        require(set(row) == {'steps', 'earlier_exact', 'new_exact'} and all(type(row[k]) is int and 0 <= row[k] <= 96
                for k in ('earlier_exact', 'new_exact')), 'closed tuning-only gate inputs required')
    eligible = [row for row in stages if row['earlier_exact'] >= parent_exact - tolerance]
    return max(eligible, key=lambda row: (row['new_exact'], row['earlier_exact'], -row['steps'])) if eligible else None


def verify_panel_inventory(items, generations):
    expected = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS} | {f'parent-{seed}' for seed in SEEDS}
    require(len(items) == 9 and {r['name'] for r in items} == expected and set(generations) == expected,
            'six selected arm slots and three unchanged parent slots required')
    total = 0
    for item in items:
        required = set(PANEL_COUNTS)
        if item['decoder_kind'] == 'mixed' and item['enabled']:
            required.add('fresh_disabled')
        require(set(generations[item['name']]) == required, 'complete selected model/panel inventory required')
        total += sum(144 if panel == 'fresh_disabled' else PANEL_COUNTS[panel] for panel in required)
    require(6102 <= total <= 6534, 'selected-model numerical denominator differs')
    return total


def annotated_metrics(generation, sources, references, *, supervised_trigger):
    result = previous.score(generation['rows'], sources, references)
    counts, confusion = Counter(), Counter()
    targets = {row['id']: row for row in references}
    for prediction, source in zip(generation['rows'], sources):
        target = targets[source['id']]
        wanted = target['canonical_ir']['rules'][0]['modality']
        actual = prediction['canonical_ir']['rules'][0]['modality'] if prediction['status'] == 'decoded' else 'abstained'
        confusion[wanted + '->' + actual] += 1
        coordinates = target.get('facet_spans')
        if coordinates is not None:
            counts['actor_annotated_count'] += 1
            actor = prediction.get('span_diagnostics', {}).get('facets', {}).get('actor', {})
            wanted_start, wanted_end = coordinates['actor']
            start, end = actor.get('char_start') == wanted_start, actor.get('char_end') == wanted_end
            counts['actor_start_exact'] += start; counts['actor_end_exact'] += end
            counts['actor_span_exact'] += start and end
            counts['actor_span_exact_on_decoded'] += start and end and prediction['status'] == 'decoded'
        trigger = target.get('trigger_span')
        if trigger is not None:
            counts['trigger_annotated_count'] += 1
            if supervised_trigger:
                diagnostic = prediction.get('grounding_diagnostics', {}).get('trigger', {})
                counts['trigger_span_exact'] += [diagnostic.get('char_start'), diagnostic.get('char_end')] == trigger
    for key in ('actor_annotated_count', 'actor_start_exact', 'actor_end_exact', 'actor_span_exact',
                'actor_span_exact_on_decoded', 'trigger_annotated_count'):
        counts.setdefault(key, 0)
    return {**result, **dict(counts), 'modality_confusion': dict(confusion),
        'trigger_evaluation_available': supervised_trigger,
        'trigger_span_exact': counts['trigger_span_exact'] if supervised_trigger else None,
        'actor_coordinate_metrics_include_abstained_diagnostics': True,
        'auxiliary_trigger_metric_scope': 'Only genuinely supervised mixed heads; no trigger annotation synthesized for earlier rows'}


def verify_fitting_provenance(inputs):
    """Rejoin original annotations independently; never locate missing triggers."""
    manifest = inputs['manifest']
    old = read_ref(manifest['inputs']['earlier_corpus'])
    new_manifest = read_ref(manifest['inputs']['new_curriculum'])
    old_expected, new_expected = {}, {}
    for source_split, output_split in (('train', 'train'), ('tuning', 'tuning')):
        old_expected[output_split] = []
        for original in old['splits'][source_split]:
            facets = {}
            for field in ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal'):
                recorded = original['source_spans'][field]
                if field in ('conditions', 'exceptions', 'temporal'):
                    require(type(recorded) is list and len(recorded) <= 1, 'earlier qualifier coordinates exceed inherited singleton profile')
                    facets[field] = recorded[0] if recorded else None
                else:
                    facets[field] = recorded or None
            old_expected[output_split].append({key: original[key] for key in ('id', 'source_text', 'canonical_ir')} |
                {'facet_spans': facets, 'domain': 'earlier', 'trigger_span': None, 'trigger_supervised': False})
        new_expected[output_split] = [{**row, 'domain': 'new', 'trigger_supervised': True}
            for row in read_ref(new_manifest['artifacts'][source_split])]
    require(inputs['training'] == old_expected['train'] + new_expected['train'], 'mixed training rows differ from original frozen source/coordinate labels')
    require(inputs['tuning']['earlier'] == old_expected['tuning'] and inputs['tuning']['new'] == new_expected['tuning'],
            'mixed tuning annotations differ from original coordinate provenance')
    return {'earlier_training_rows': len(old_expected['train']), 'new_training_rows': len(new_expected['train']),
        'earlier_tuning_rows': len(old_expected['tuning']), 'new_tuning_rows': len(new_expected['tuning']),
        'earlier_trigger_labels_synthesized': False, 'original_facet_coordinate_joins_verified': True,
        'original_inputs': manifest['inputs']}


@lru_cache(maxsize=256)
def audit_pool_order(count, seed, domain, epoch):
    order = list(range(count))
    random.Random(f"mixed-replay/v1:{seed}:{domain}:{epoch}").shuffle(order)
    return tuple(order)


def expected_batch(seed, step, pools):
    """Independent direct position calculation; does not call model sampler."""
    result = {}
    for domain, rows in pools.items():
        indices = []
        for position in range((step - 1) * 6, step * 6):
            epoch, cursor = divmod(position, len(rows))
            indices.append(audit_pool_order(len(rows), seed, domain, epoch)[cursor])
        result[domain] = indices
    return result


def verify_batch_report(report, predecessor, checkpoint, training, *, enabled):
    pools = {domain: [row for row in training if row['domain'] == domain] for domain in ('earlier', 'new')}
    start = predecessor['progress']['optimizer_steps']
    finish = checkpoint['progress']['optimizer_steps']
    require(finish - start == 400 and report['optimizer_steps'] == 400 and report['training_executed'] is True
        and report['new_optimizer_steps_total'] == finish and report['stopped_reason'] == 'step_limit', 'complete400-step training stage required')
    require(len(report['batch_exposures']) == len(report['batch_loss_components']) == len(report['batch_losses']) == 400,
            'complete per-batch training evidence required')
    require(report['checkpoint_sha256'] == digest(checkpoint) and report['domain_exposures'] == {'earlier': 2400, 'new': 2400},
            'stage checkpoint or balanced exposure count differs')
    seen = {'earlier': Counter(), 'new': Counter()}
    for ordinal, (exposure, parts, loss) in enumerate(zip(report['batch_exposures'], report['batch_loss_components'], report['batch_losses']), start + 1):
        indices = expected_batch(checkpoint['config']['seed'], ordinal, pools)
        ids = {domain: [pools[domain][i]['id'] for i in values] for domain, values in indices.items()}
        require(exposure == {'optimizer_step': ordinal, 'indices_by_domain': indices, 'ids_by_domain': ids},
                'deterministic six-plus-six batch source exposure differs')
        for domain in pools: seen[domain].update(ids[domain])
        require(parts['domain_rows'] == {'earlier': 6, 'new': 6} and parts['supervised_trigger_rows'] == 6
            and parts['trigger_loss_rows'] == (6 if enabled else 0)
            and parts['actor_loss_rows_by_domain'] == {domain: 6 if enabled else 0 for domain in pools},
                'old trigger mask or domain objective counts differ')
        names = ('semantic', 'trigger', 'actor', 'semantic_earlier', 'semantic_new', 'actor_earlier', 'actor_new')
        require(all(type(parts[key]) in (int, float) and math.isfinite(parts[key]) and parts[key] >= 0 for key in names)
            and type(loss) in (int, float) and math.isfinite(loss), 'finite nonnegative loss components required')
        require(math.isclose(parts['semantic'], .5 * (parts['semantic_earlier'] + parts['semantic_new']), rel_tol=3e-6, abs_tol=3e-7),
                'semantic domain weights differ')
        require(math.isclose(parts['actor'], .5 * (parts['actor_earlier'] + parts['actor_new']), rel_tol=3e-6, abs_tol=3e-7),
                'actor domain weights differ')
        if not enabled:
            require(parts['trigger'] == parts['actor'] == parts['actor_earlier'] == parts['actor_new'] == 0., 'disabled auxiliary loss is nonzero')
        expected_loss = parts['semantic'] + checkpoint['config']['trigger_loss_weight'] * parts['trigger'] + checkpoint['config']['actor_loss_weight'] * parts['actor']
        require(math.isclose(loss, expected_loss, rel_tol=3e-6, abs_tol=3e-7), 'total objective differs from recorded domain/masked losses')
    actual_changes = sorted(name for name in checkpoint['model_state'] if checkpoint['model_state'][name] != predecessor['model_state'][name])
    require(len(set(report['changed_parameter_names'])) == len(report['changed_parameter_names'])
        and sorted(report['changed_parameter_names']) == actual_changes, 'changed parameter inventory differs')
    if not enabled:
        require(all(value == 0. for value in report['auxiliary_gradient_norm_max'].values()), 'disabled grounding head gradient is nonzero')
        require(all(checkpoint['model_state'][name] == predecessor['model_state'][name] for name in checkpoint['model_state']
            if name.startswith(('trigger_boundary.', 'trigger_modality.', 'actor_boundary.'))), 'disabled auxiliary parameters changed')
    for domain, rows in pools.items():
        epochs, cursor = divmod(finish * 6, len(rows))
        order = list(range(len(rows))); random.Random(f"mixed-replay/v1:{checkpoint['config']['seed']}:{domain}:{epochs}").shuffle(order)
        require(checkpoint['progress']['pools'][domain] == {'epochs_completed': epochs, 'row_cursor': cursor, 'shuffle_order': order},
                'independent sampler checkpoint progression differs')
    return {'steps': finish, 'domain_exposures': report['domain_exposures'],
        'unique_domain_rows_seen_this_stage': {domain: len(counts) for domain, counts in seen.items()},
        'batch_trace_sha256': digest(report['batch_exposures']), 'six_plus_six_and_missing_trigger_mask_verified': True,
        'loss_accounting_verified': True, 'optimizer_trajectory_replayed': False}


def replay_job(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    item = job['model']; parent = item['decoder_kind'] == 'parent'
    module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if parent else (mixed, mixed.MixedReplayDecoder)
    checkpoint = module.load_checkpoint(item['checkpoint']['path'], expected_sha256=item['checkpoint']['sha256'])
    expected = read_ref(job['generation'])
    if job.get('stage'): expected = expected['generation']
    actual = previous.generate(cls(checkpoint), job['sources'], parent=parent, ablation=job['ablation'])
    require(actual == expected, 'fresh selected/stage inference and recorded diagnostics differ: ' + job['name'])
    copied = sum(source_audit.assert_source_copy(prediction, source) for prediction, source in zip(actual['rows'], job['sources']))
    return {'name': job['name'], 'rows': len(job['sources']), 'generation': job['generation'], 'checkpoint': item['checkpoint'],
        'source_inputs_sha256': digest(job['sources']), 'recorded_generation_sha256': digest(actual),
        'exact_recorded_payload_replay': True, 'copied_facets_verified': copied, 'target_access': False,
        'stage_tuning': job.get('stage', False)}


def verify_training(inputs, heads, frozen):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    require(len(heads) == 6 and {r['name'] for r in heads} == {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS},
            'complete six trained trials required')
    jobs, audits, common = [], [], {}
    combined_tuning = inputs['tuning']['earlier'] + inputs['tuning']['new']
    by_name = {item['name']: item for item in frozen['models']}
    for seed in SEEDS:
        baseline = by_name[f'parent-{seed}']
        require(baseline['arm'] == 'parent' and baseline['seed'] == seed and baseline['checkpoint'] == inputs['parents'][seed]
            and baseline['decoder_kind'] == 'parent' and baseline['selection'] == 'unchanged_parent'
            and baseline['selected_steps'] == baseline['executed_steps'] == 0 and baseline['enabled'] is False,
                'unchanged parent slot attribution differs')
    for head in heads:
        arm, seed, name = head['arm'], head['seed'], head['name']
        require(head == by_name[name] and name == f'{arm}-{seed}' and head['requested_enabled'] is ARMS[arm]
            and head['parent'] == inputs['parents'][seed] and head['executed_steps'] == 800, 'selected trial/source parent binding differs')
        parent_ref = head['parent']; parent = dimensions.load_checkpoint(parent_ref['path'], expected_sha256=parent_ref['sha256'])
        initial = mixed.build_checkpoint(parent, inputs['training'], combined_tuning, trigger_enabled=ARMS[arm], learning_rate=.001, batch_size=12)
        require(initial['optimizer_state'] == {'schema': 'adam-default-betas-eps/v1', 'parameters': {}}
            and initial['progress']['optimizer_steps'] == 0, 'fresh Adam initialization required')
        initial_source = {k: v for k, v in initial['model_state'].items() if not k.startswith(('trigger_boundary.', 'trigger_modality.', 'actor_boundary.'))}
        require(initial_source == parent['model_state'], 'copied parent source tensors differ')
        require(digest(initial) == head['initial_checkpoint_sha256'], 'initial checkpoint reconstruction differs')
        common.setdefault(seed, set()).add(digest(initial['model_state']))
        receipt = read_ref(head['initialization'])
        require(receipt['parent'] == parent_ref and receipt['checkpoint_sha256'] == digest(initial)
            and receipt['source_model_sha256'] == digest(parent['model_state'])
            and receipt['all_tuning_source_predictions_and_recorded_span_logits_equal'] is True, 'initialization receipt differs')
        parent_scores = {}
        for domain in ('earlier', 'new'):
            saved = receipt['panels'][domain]
            require(previous.comparable(saved['parent_generation']) == previous.comparable(saved['initial_generation']), 'initial source diagnostic parity differs')
            require(saved['parent_generation'] == read_ref(frozen['files'][f'parent-{seed}']['tuning_' + domain]),
                    'initial parent tuning differs from frozen parent panel')
            metric = previous.score(saved['parent_generation']['rows'], inputs['sources']['tuning_' + domain], inputs['tuning'][domain])
            require(metric == saved['parent_metrics'], 'parent gate baseline score differs')
            parent_scores[domain] = metric['exact']
        require(parent_scores == head['parent_tuning_exact'], 'retention baseline tuning counts differ')
        require([r['steps'] for r in head['stages']] == [400, 800], 'both400/800 candidate checkpoints required')
        checkpoint, normalized, exposure_audits = initial, [], []
        for stage in head['stages']:
            preceding = checkpoint
            checkpoint = mixed.load_checkpoint(stage['checkpoint']['path'], expected_sha256=stage['checkpoint']['sha256'])
            require(stage['previous_checkpoint_sha256'] == checkpoint['parent_checkpoint_sha256'] == digest(preceding)
                and checkpoint['progress']['optimizer_steps'] == stage['steps'], 'candidate checkpoint/resumption chain differs')
            for key in ('config', 'training_manifest_sha256', 'tuning_manifest_sha256', 'training_count', 'tuning_count',
                        'training_domain_counts', 'tuning_domain_counts', 'source_parent_checkpoint_sha256',
                        'initial_source_model_sha256', 'initial_model_state_sha256'):
                require(checkpoint[key] == initial[key], 'candidate altered original initialization or fitting manifest: ' + key)
            exposure_audits.append(verify_batch_report(read_ref(stage['training_report']), preceding, checkpoint, inputs['training'], enabled=ARMS[arm]))
            numbers = {'steps': stage['steps']}
            for domain in ('earlier', 'new'):
                tuned = read_ref(stage['tuning_' + domain]); source = inputs['sources']['tuning_' + domain]
                measured = previous.score(tuned['generation']['rows'], source, inputs['tuning'][domain])
                require(tuned['metrics'] == measured and stage['tuning_' + domain + '_exact'] == measured['exact'], 'candidate tuning score differs')
                numbers[domain + '_exact'] = measured['exact']
                jobs.append({'name': f"{name}/stage-{stage['steps']}/tuning_{domain}",
                    'model': {**head, 'checkpoint': stage['checkpoint'], 'decoder_kind': 'mixed'},
                    'sources': source, 'generation': stage['tuning_' + domain], 'ablation': 'none', 'stage': True})
            require(stage['retention_eligible'] is (numbers['earlier_exact'] >= parent_scores['earlier'] - 1), 'candidate eligibility declaration differs')
            normalized.append(numbers)
        chosen = retention_choice(normalized, parent_scores['earlier'])
        if chosen is None:
            require(head['selection'] == 'parent_fallback' and head['decoder_kind'] == 'parent'
                and head['enabled'] is False and head['selected_steps'] == 0 and head['checkpoint'] == parent_ref,
                    'failed retention gate must select unchanged parent')
        else:
            stage = next(r for r in head['stages'] if r['steps'] == chosen['steps'])
            require(head['selection'] == 'candidate' and head['decoder_kind'] == 'mixed'
                and head['enabled'] is ARMS[arm] and head['selected_steps'] == stage['steps'] and head['checkpoint'] == stage['checkpoint'],
                    'selected checkpoint differs from independent tuning-only retention gate')
            for domain in ('earlier', 'new'):
                require(read_ref(stage['tuning_' + domain])['generation'] == read_ref(frozen['files'][name]['tuning_' + domain]),
                        'selected tuning differs from retained candidate')
        audits.append({'name': name, 'initial_full_model_sha256': digest(initial['model_state']),
            'parent_tuning_exact': parent_scores, 'stage_tuning': normalized, 'stage_exposure_audits': exposure_audits,
            'selected_steps': head['selected_steps'], 'selection': head['selection'], 'fresh_adam_state_verified': True,
            'initial_tensors_and_resumption_chain_verified': True, 'optimizer_trajectory_replayed': False})
    require(all(len(values) == 1 for values in common.values()), 'same-seed initial full model tensors differ across arms')
    return jobs, audits


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_mixed_replay_experiment as runner
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(1 <= args.workers <= 3, 'one to three replay workers required')
    directory, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    frozen_ref = ref(directory / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == runner.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['challenge_targets_opened'] is False and frozen['regression_targets_opened'] is False
        and frozen['executed_optimizer_updates'] == 4800, 'complete source-only training/generation freeze required')
    plan = read_ref(frozen['plan'])
    require(plan['arms'] == ARMS and plan['seeds'] == list(SEEDS) and plan['stage_steps'] == 400 and plan['stages'] == 2
        and plan['retention_tolerance'] == 1 and plan['counts'] == PANEL_COUNTS
        and plan['domain_batch_sizes'] == {'earlier': 6, 'new': 6}
        and plan['training_domain_counts'] == {'earlier': 1152, 'new': 600}
        and plan['challenge_target_access'] is False and plan['regression_target_access'] is False,
            'matched predeclared balanced-replay plan differs')
    require(all(sha(path) == wanted for path, wanted in plan['producer_pins'].items()), 'frozen fitting implementation drift')
    inputs = runner.load_config(plan['config']['path'])
    read_ref(plan['config'], parse=False)
    require(inputs['sources'] == read_ref(frozen['sources']), 'frozen source panels differ from original inputs')
    provenance = verify_fitting_provenance(inputs)
    heads = read_ref(frozen['heads']); items = frozen['models']
    total_main_rows = verify_panel_inventory(items, frozen['files'])
    require(frozen['retention_gate_failures'] == [row['name'] for row in heads if row['selection'] == 'parent_fallback'],
            'retention fallback inventory differs')
    output.mkdir(parents=True, exist_ok=False)
    pins = dict(plan['producer_pins'])
    for module in (sys.modules[__name__], runner, previous, calendar, calendar_summary, source_audit, gate):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    jobs, training_audits = verify_training(inputs, heads, frozen)
    training_ref = write(output / 'training-and-selection-audit.json', {'models': training_audits,
        'fitting_annotation_provenance': provenance, 'same_seed_initial_model_tensors_equal': True,
        'selected_stage_uses_tuning_only': True, 'optimizer_trajectory_replayed': False,
        'actual_optimizer_updates_recorded': 4800, 'recorded_training_exposures': {'earlier': 28800, 'new': 28800}, **FALSE})
    generations = {}
    for item in items:
        name = item['name']; generations[name] = {}
        for panel, reference in frozen['files'][name].items():
            sources = inputs['sources']['fresh' if panel == 'fresh_disabled' else panel]
            generation = read_ref(reference)
            require(len(generation['rows']) == len(sources), 'complete selected source generation count required')
            generations[name][panel] = generation
            jobs.append({'name': name + '/' + panel, 'model': item, 'sources': sources, 'generation': reference,
                'ablation': 'disabled' if panel == 'fresh_disabled' else 'none'})
    require(sum(len(job['sources']) for job in jobs if job.get('stage')) == 2304
        and sum(len(job['sources']) for job in jobs if not job.get('stage')) == total_main_rows,
            'full stage-tune and selected-generation replay denominators differ')
    replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(replay_job, job) for job in jobs]):
            replay = future.result(); replays.append(replay)
            print({'phase': 'replayed', 'panel': replay['name'], 'rows': replay['rows']}, flush=True)
    for item in heads:
        if item['selection'] == 'parent_fallback':
            require(generations[item['name']] == generations[f"parent-{item['seed']}"], 'parent fallback outputs differ from unchanged parent slot')
    replay_ref = write(output / 'replay-frozen.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'panels': sorted(replays, key=lambda row: row['name']), 'rows': sum(r['rows'] for r in replays),
        'stage_tuning_rows': 2304, 'selected_model_rows': total_main_rows, 'training_audit': training_ref,
        'fresh_and_regression_targets_opened': False, 'unselected_candidate_test_outputs_generated': False, **FALSE})
    selections = {}
    for item in items:
        name = item['name']
        value = calendar.select_candidates(inputs['sources']['fresh'], generations[name]['fresh']['rows'],
            toolchain=args.toolchain, policy=calendar.POLICY)
        lookup = {source['id']: (source, prediction) for source, prediction in zip(inputs['sources']['fresh'], generations[name]['fresh']['rows'])}
        for entry in value['rows']:
            source, prediction = lookup[entry['candidate']['candidate_id']]
            calendar_summary.verify_entry(source, prediction, entry)
        require(value['source_count'] == len(value['rows']) + len(value['excluded']) == 144, 'fresh build selection dropped rows')
        selections[name] = value
    selected_ref = write(output / 'build-selection-frozen.json', {'models': selections, 'replay': replay_ref,
        'source_count': 1296, 'fresh_targets_opened': False, 'interpretation_policy': calendar.POLICY,
        'canonical_references_used_for_selection': False, 'semantic_scores_used_for_selection': False})
    builds = {}
    for item in items:
        name = item['name']; entries = selections[name]['rows']; builds[name] = []
        for start in range(0, len(entries), gate.MAX_ROWS):
            batch = entries[start:start + gate.MAX_ROWS]
            destination = output / 'builds' / name / f'batch-{start // gate.MAX_ROWS:02d}'
            receipt = gate.build_qualified_legal(batch, toolchain=args.toolchain, lake_executable=args.lake_executable,
                timeout_seconds=60, output_directory=destination).to_dict()
            reference = ref(destination / 'qualified-receipt.json')
            require(calendar_summary.verify_receipt(reference, batch) == receipt, 'independent native compiler receipt reconstruction differs')
            builds[name].append({'candidate_ids': [row['candidate']['candidate_id'] for row in batch], 'receipt': reference,
                'build_passed': receipt['build_passed'], 'backend_executed': receipt['backend_executed'], 'command': receipt['command']})
        print({'phase': 'built', 'model': name, 'supported_fresh_outputs': len(entries)}, flush=True)
    build_ref = write(output / 'builds-frozen.json', {'schema': SCHEMA, 'models': builds, 'selections': selected_ref,
        'replay': replay_ref, 'fresh_and_regression_targets_opened': False, **FALSE})
    # Challenge and regression targets are parsed only after the complete replay/build freeze.
    config, manifest = inputs['config'], inputs['manifest']
    target_refs = {'fresh': manifest['artifacts']['challenge_targets'], 'earlier_regression': config['earlier_regression_targets'],
                   'exposed_regression': config['exposed_regression_targets']}
    references = {'tuning_earlier': inputs['tuning']['earlier'], 'tuning_new': inputs['tuning']['new']}
    for panel, reference in target_refs.items():
        references[panel] = previous.reference_rows(read_ref(reference), inputs['sources'][panel])
        for row in references[panel]:
            if 'canonical_target_sha256' in row:
                require(row['canonical_target_sha256'] == digest(row['canonical_ir']), 'posthoc reference canonical commitment differs')
    references['fresh_disabled'] = references['fresh']
    exposure = read_ref(manifest['artifacts']['exposure_audit'])
    require(all(exposure[key] == value for key, value in manifest['exposure_summary'].items()), 'surface-exposure summary differs from frozen audit')
    metrics, models = {}, []
    for item in items:
        name = item['name']; metrics[name] = {}
        for panel, generation in generations[name].items():
            sources = inputs['sources']['fresh' if panel == 'fresh_disabled' else panel]
            metrics[name][panel] = annotated_metrics(generation, sources, references[panel],
                supervised_trigger=item['decoder_kind'] == 'mixed' and item['enabled'])
        exact = {r['id']: r['exact'] for r in metrics[name]['fresh']['rows']}
        controls = {}
        if 'fresh_disabled' in generations[name]:
            normal, disabled = generations[name]['fresh']['rows'], generations[name]['fresh_disabled']['rows']
            controls = {'count': 144, 'canonical_output_changed': sum((a['status'], a['canonical_ir']) != (b['status'], b['canonical_ir'])
                for a, b in zip(normal, disabled)),
                'recorded_prediction_changed': sum(a != b for a, b in zip(normal, disabled)),
                'normal_exact_minus_disabled': metrics[name]['fresh']['exact'] - metrics[name]['fresh_disabled']['exact']}
        models.append({'name': name, 'arm': item['arm'], 'seed': item['seed'], 'selection': item['selection'],
            'selected_steps': item['selected_steps'], 'executed_steps': item['executed_steps'], 'decoder_kind': item['decoder_kind'],
            'checkpoint': item['checkpoint'], 'requested_enabled': item['requested_enabled'], 'enabled': item['enabled'],
            'metrics': {panel: {key: value for key, value in measured.items() if key != 'rows'} for panel, measured in metrics[name].items()},
            'builds': build_accounting(selections[name], builds[name], exact), 'residual_controls': controls})
    paired = []
    for seed in SEEDS:
        for left, right in ((f'mixed_grounding-{seed}', f'mixed_continuation-{seed}'),
                            (f'mixed_continuation-{seed}', f'parent-{seed}'), (f'mixed_grounding-{seed}', f'parent-{seed}')):
            for panel in ('fresh', 'earlier_regression', 'exposed_regression'):
                paired.append({'left': left, 'right': right, 'panel': panel, **previous.paired(metrics[left][panel], metrics[right][panel])})
    totals = {}
    for arm in (*ARMS, 'parent'):
        group = [row for row in models if row['arm'] == arm]
        totals[arm] = {panel: {key: sum(row['metrics'][panel][key] for row in group)
            for key in ('count', 'decoded', 'abstained', 'exact')} for panel in PANEL_COUNTS}
        totals[arm]['builds'] = {key: sum(row['builds'][key] for row in group)
            for key in ('count', 'decoded', 'abstained', 'built', 'built_exact', 'built_reference_mismatch', 'build_invocations')}
        totals[arm]['fallbacks'] = sum(row['selection'] == 'parent_fallback' for row in group)
    details_ref = write(output / 'scored-details.json', metrics)
    require(all(sha(path) == wanted for path, wanted in pins.items()), 'qualification or producer source drift')
    for reference in [frozen_ref, frozen['plan'], frozen['heads'], frozen['sources'], plan['config'],
                      *target_refs.values(), manifest['artifacts']['exposure_audit'],
                      *[value for panels in frozen['files'].values() for value in panels.values()],
                      *[stage[key] for head in heads for stage in head['stages'] for key in
                        ('checkpoint', 'training_report', 'tuning_earlier', 'tuning_new')]]:
        read_ref(reference, parse=False)
    result = {'schema': SCHEMA, 'generation_freeze': frozen_ref, 'training_selection_audit': training_ref,
        'replay': replay_ref, 'builds': build_ref, 'details': details_ref, 'producer_pins': pins,
        'models': models, 'totals': totals, 'paired_comparisons': paired,
        'replayed_rows': sum(r['rows'] for r in replays), 'retention_gate_failures': frozen['retention_gate_failures'],
        'executed_optimizer_updates': 4800, 'training_domain_exposures': {'earlier': 28800, 'new': 28800},
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes': True,
        'test_results_used_for_selection_or_gate_revision': False, 'unselected_candidate_test_scores_computed': False,
        'source_coordinate_provenance_verified': True, 'surface_exposure_audit': manifest['artifacts']['exposure_audit'],
        'surface_exposure_summary': manifest['exposure_summary'],
        'fresh_panel_scope': '144 newly authored source-disjoint examples; inherited rendering-family novelty is not claimed',
        'regression_scopes': {'earlier_regression': '192 previously exposed authored examples',
                              'exposed_regression': '150 previously exposed grounding challenge examples'},
        'scope': 'Fixed old/new replay, explicit retention gate with unchanged-parent fallback, and restricted source-copy/calendar validation; no full logic-family or statutory qualification',
        'actual_lake_build_executed': any(batch['backend_executed'] for batches in builds.values() for batch in batches),
        **FALSE}
    write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'totals': totals, 'fallbacks': frozen['retention_gate_failures']}, flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--lake-executable', required=True); parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    parser.add_argument('--workers', type=int, default=3)
    run(parser.parse_args())
