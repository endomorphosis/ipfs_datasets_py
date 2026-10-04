#!/usr/bin/env python3
"""Independent replay, retention, provenance and compiler audit of temporal curricula.

The two curricula share architecture, losses, source parents and fixed update
budgets. Compilation precedes fresh/reference scoring; no optimizer trajectory
reexecution or general legal/logic-family qualification is claimed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_mixed_replay_experiment as prior
from scripts.ops.legal_ir import run_legal_grounding_experiment as previous
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary
from scripts.ops.legal_ir import summarize_legal_native_conditioning_experiment as source_audit

require, digest, read_ref, ref, write, sha = prior.require, prior.digest, prior.read_ref, prior.ref, prior.write, prior.sha
SCHEMA = 'legal-temporal-curriculum-independent-qualification/v1'
SEEDS = prior.SEEDS
ARMS = {'baseline_continuation': {'curriculum': 'baseline', 'architecture': 'continuation', 'enabled': False},
        'baseline_grounding': {'curriculum': 'baseline', 'architecture': 'grounding', 'enabled': True},
        'temporal_augmented_continuation': {'curriculum': 'temporal_augmented', 'architecture': 'continuation', 'enabled': False},
        'temporal_augmented_grounding': {'curriculum': 'temporal_augmented', 'architecture': 'grounding', 'enabled': True}}
TUNING_COUNTS = {'earlier': 96, 'prior_new': 96, 'temporal': 120}
PANEL_COUNTS = {'tuning_earlier': 96, 'tuning_prior_new': 96, 'tuning_temporal': 120,
                'fresh': 180, 'earlier_regression': 192, 'exposed_regression': 150, 'mixed_regression': 144}
FALSE = prior.FALSE


def retention_choice(stages, parent_exact):
    """Independent closed tuning policy; no challenge metrics are admitted."""
    require(type(parent_exact) is int and 0 <= parent_exact <= 96, 'bounded parent tuning score required')
    require(type(stages) is list and len(stages) == 2 and [r['steps'] for r in stages] == [400, 800],
            'both fixed training stages required')
    for row in stages:
        require(set(row) == {'steps', 'earlier_exact', 'prior_new_exact', 'temporal_exact'}
            and all(type(row[domain + '_exact']) is int and 0 <= row[domain + '_exact'] <= count
                    for domain, count in TUNING_COUNTS.items()), 'closed tuning-only gate inputs required')
    eligible = [row for row in stages if row['earlier_exact'] >= parent_exact - 1]
    return max(eligible, key=lambda row: (row['temporal_exact'], row['prior_new_exact'], row['earlier_exact'], -row['steps'])) if eligible else None


def verify_panel_inventory(items, generations):
    expected = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS} | {f'parent-{seed}' for seed in SEEDS}
    require(len(items) == 15 and {r['name'] for r in items} == expected and set(generations) == expected,
            'twelve selected arm slots and three unchanged parents required')
    total = 0
    for item in items:
        panels = set(PANEL_COUNTS)
        if item['decoder_kind'] == 'mixed' and item['enabled']:
            panels.add('fresh_disabled')
        require(set(generations[item['name']]) == panels, 'complete selected model/panel inventory required')
        total += sum(180 if panel == 'fresh_disabled' else PANEL_COUNTS[panel] for panel in panels)
    require(14670 <= total <= 15750, 'selected-model numerical denominator differs')
    return total


def compare_baseline_stage(current, historical):
    """Evaluation-panel metadata can differ; fitted numeric trajectories cannot."""
    fields = ('model_state', 'optimizer_state', 'progress')
    require(all(current[key] == historical[key] for key in fields), 'baseline numeric checkpoint differs from prior fixed replay trajectory')
    return {key + '_sha256': digest(current[key]) for key in fields}


def subgroup_exposure(report, training, baseline_ids):
    """Count actual sampled rows, keeping new original versus new temporal distinct."""
    original = set(baseline_ids)
    newer = [row for row in training if row['domain'] == 'new']
    counts = {'prior_new': 0, 'temporal_additions': 0}
    for batch in report['batch_exposures']:
        for index in batch['indices_by_domain']['new']:
            counts['prior_new' if newer[index]['id'] in original else 'temporal_additions'] += 1
    require(sum(counts.values()) == 2400, 'complete per-stage new domain exposure required')
    return counts


def replay_job(job):
    # Frozen helper restores a fresh model, compares every recorded output and
    # diagnostic, and independently verifies source-copy coordinates.
    return prior.replay_job(job)


def verify_fitting_provenance(inputs):
    manifest = inputs['manifest']
    mixed_manifest = read_ref(manifest['inputs']['mixed_corpus'])
    baseline = read_ref(mixed_manifest['artifacts']['train'])
    additions = read_ref(manifest['artifacts']['temporal_training'])
    require(inputs['training']['baseline'] == baseline and inputs['training']['temporal_augmented'] == baseline + additions,
            'curricula differ from ordered baseline and declared temporal additions')
    require(len(additions) == 600 and all(row['domain'] == 'new' and row['trigger_supervised'] is True
            and row['trigger_span'] is not None for row in additions), '600 explicitly supervised temporal additions required')
    earlier = read_ref(mixed_manifest['artifacts']['tuning_earlier'])
    newer = read_ref(mixed_manifest['artifacts']['tuning_new'])
    require(inputs['tuning']['earlier'] == earlier and inputs['tuning']['prior_new'] == newer,
            'common original tuning panels changed')
    inherited = prior.verify_fitting_provenance({'manifest': mixed_manifest, 'training': baseline,
        'tuning': {'earlier': earlier, 'new': newer}})
    return {'original_annotation_provenance': inherited, 'baseline_exact_order_preserved': True,
        'appended_temporal_rows': len(additions), 'appended_temporal_reference': manifest['artifacts']['temporal_training'],
        'earlier_trigger_labels_synthesized': False, 'common_tuning_counts': {k: len(v) for k, v in inputs['tuning'].items()}}


def verify_training(inputs, heads, frozen):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    require(len(heads) == 12 and {row['name'] for row in heads} == {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS},
            'complete twelve trained trials required')
    jobs, audits, common = [], [], {}
    combined_tuning = [row for panel in TUNING_COUNTS for row in inputs['tuning'][panel]]
    by_name = {item['name']: item for item in frozen['models']}
    historical_heads = read_ref(inputs['config']['baseline_reference_heads'])
    historical = {row['name']: row for row in historical_heads}
    require(len(historical_heads) == 6 and set(historical) == {f'mixed_{architecture}-{seed}'
        for architecture in ('continuation', 'grounding') for seed in SEEDS}, 'complete original baseline stage inventory required')
    baseline_reproductions = 0
    baseline_ids = [row['id'] for row in inputs['training']['baseline']]
    for seed in SEEDS:
        baseline = by_name[f'parent-{seed}']
        require(baseline['arm'] == baseline['architecture'] == baseline['curriculum'] == 'parent'
            and baseline['seed'] == seed and baseline['checkpoint'] == inputs['parents'][seed]
            and baseline['decoder_kind'] == 'parent' and baseline['selection'] == 'unchanged_parent'
            and baseline['selected_steps'] == baseline['executed_steps'] == 0
            and baseline['enabled'] is baseline['requested_enabled'] is False, 'unchanged parent slot attribution differs')
    for head in heads:
        arm, seed, name = head['arm'], head['seed'], head['name']
        settings = ARMS[arm]; enabled = settings['enabled']; curriculum = settings['curriculum']
        require(head == by_name[name] and name == f'{arm}-{seed}' and head['requested_enabled'] is enabled
            and head['curriculum'] == curriculum and head['architecture'] == settings['architecture']
            and head['parent'] == inputs['parents'][seed] and head['executed_steps'] == 800,
                'selected trial/source parent/curriculum binding differs')
        training = inputs['training'][curriculum]
        parent_ref = head['parent']; parent = dimensions.load_checkpoint(parent_ref['path'], expected_sha256=parent_ref['sha256'])
        initial = mixed.build_checkpoint(parent, training, combined_tuning, trigger_enabled=enabled, learning_rate=.001, batch_size=12)
        require(initial['optimizer_state'] == {'schema': 'adam-default-betas-eps/v1', 'parameters': {}}
            and initial['progress']['optimizer_steps'] == 0, 'fresh Adam initialization required')
        source_state = {key: value for key, value in initial['model_state'].items()
            if not key.startswith(('trigger_boundary.', 'trigger_modality.', 'actor_boundary.'))}
        require(source_state == parent['model_state'], 'copied original parent tensors differ')
        require(digest(initial) == head['initial_checkpoint_sha256']
            and digest(initial['model_state']) == head['initial_model_state_sha256']
            and digest(source_state) == head['initial_source_model_sha256'], 'initial checkpoint/tensor reconstruction differs')
        common.setdefault(seed, set()).add(digest(initial['model_state']))
        receipt = read_ref(head['initialization'])
        require(receipt['parent'] == parent_ref and receipt['checkpoint_sha256'] == digest(initial)
            and receipt['source_model_sha256'] == digest(source_state)
            and receipt['all_tuning_source_predictions_and_recorded_span_logits_equal'] is True, 'initialization receipt differs')
        parent_scores = {}
        for panel in TUNING_COUNTS:
            saved = receipt['panels'][panel]
            require(previous.comparable(saved['parent_generation']) == previous.comparable(saved['initial_generation']),
                    'initial source diagnostic parity differs')
            require(saved['parent_generation'] == read_ref(frozen['files'][f'parent-{seed}']['tuning_' + panel]),
                    'initial parent tuning differs from frozen parent panel')
            metric = previous.score(saved['parent_generation']['rows'], inputs['sources']['tuning_' + panel], inputs['tuning'][panel])
            require(metric == saved['parent_metrics'], 'parent gate baseline score differs')
            parent_scores[panel] = metric['exact']
        require(parent_scores == head['parent_tuning_exact'], 'retention baseline tuning counts differ')
        require([row['steps'] for row in head['stages']] == [400, 800], 'both400/800 candidate checkpoints required')
        checkpoint, normalized, exposure_audits, reproductions = initial, [], [], []
        for stage in head['stages']:
            preceding = checkpoint
            checkpoint = mixed.load_checkpoint(stage['checkpoint']['path'], expected_sha256=stage['checkpoint']['sha256'])
            require(stage['previous_checkpoint_sha256'] == checkpoint['parent_checkpoint_sha256'] == digest(preceding)
                and checkpoint['progress']['optimizer_steps'] == stage['steps'], 'candidate checkpoint/resumption chain differs')
            for key in ('config', 'training_manifest_sha256', 'tuning_manifest_sha256', 'training_count', 'tuning_count',
                        'training_domain_counts', 'tuning_domain_counts', 'source_parent_checkpoint_sha256',
                        'initial_source_model_sha256', 'initial_model_state_sha256'):
                require(checkpoint[key] == initial[key], 'candidate altered fitting provenance: ' + key)
            report = read_ref(stage['training_report'])
            audit = prior.verify_batch_report(report, preceding, checkpoint, training, enabled=enabled)
            audit['new_domain_subgroup_exposures'] = subgroup_exposure(report, training, baseline_ids)
            expected_groups = {'prior_new': 2400, 'temporal_additions': 0} if curriculum == 'baseline' else {'prior_new': 1200, 'temporal_additions': 1200}
            require(audit['new_domain_subgroup_exposures'] == expected_groups, 'fixed stage subgroup exposure differs')
            exposure_audits.append(audit)
            if curriculum == 'baseline':
                historical_head = historical[f"mixed_{settings['architecture']}-{seed}"]
                require(historical_head['parent'] == parent_ref and historical_head['requested_enabled'] is enabled,
                        'historical baseline source or architecture differs')
                prior_stage = next(row for row in historical_head['stages'] if row['steps'] == stage['steps'])
                prior_cp = mixed.load_checkpoint(prior_stage['checkpoint']['path'], expected_sha256=prior_stage['checkpoint']['sha256'])
                require(checkpoint['config'] == prior_cp['config']
                    and checkpoint['training_manifest_sha256'] == prior_cp['training_manifest_sha256']
                    and checkpoint['source_parent_checkpoint_sha256'] == prior_cp['source_parent_checkpoint_sha256'],
                        'baseline original configuration/training/parent differs')
                equality = compare_baseline_stage(checkpoint, prior_cp)
                reproduction = stage['baseline_reproduction']
                require(reproduction['previous_checkpoint'] == prior_stage['checkpoint']
                    and reproduction['model_state_exact'] is reproduction['optimizer_moments_exact'] is reproduction['sampler_progress_exact'] is True
                    and reproduction['model_state_sha256'] == equality['model_state_sha256']
                    and reproduction['optimizer_state_sha256'] == equality['optimizer_state_sha256'], 'baseline reproduction receipt differs')
                reproductions.append({'steps': stage['steps'], 'historical_checkpoint': prior_stage['checkpoint'], **equality})
                baseline_reproductions += 1
            else:
                require(stage['baseline_reproduction'] is None, 'augmented training cannot claim identical baseline trajectory')
            numbers = {'steps': stage['steps']}
            for panel in TUNING_COUNTS:
                tuned = read_ref(stage['tuning_' + panel]); sources = inputs['sources']['tuning_' + panel]
                measured = previous.score(tuned['generation']['rows'], sources, inputs['tuning'][panel])
                require(tuned['metrics'] == measured and stage['tuning_' + panel + '_exact'] == measured['exact'], 'candidate tuning score differs')
                numbers[panel + '_exact'] = measured['exact']
                jobs.append({'name': f"{name}/stage-{stage['steps']}/tuning_{panel}",
                    'model': {**head, 'checkpoint': stage['checkpoint'], 'decoder_kind': 'mixed'},
                    'sources': sources, 'generation': stage['tuning_' + panel], 'ablation': 'none', 'stage': True})
            require(stage['retention_eligible'] is (numbers['earlier_exact'] >= parent_scores['earlier'] - 1), 'candidate eligibility declaration differs')
            normalized.append(numbers)
        chosen = retention_choice(normalized, parent_scores['earlier'])
        if chosen is None:
            require(head['selection'] == 'parent_fallback' and head['decoder_kind'] == 'parent'
                and head['enabled'] is False and head['selected_steps'] == 0 and head['checkpoint'] == parent_ref,
                    'failed retention gate must select unchanged parent')
        else:
            stage = next(row for row in head['stages'] if row['steps'] == chosen['steps'])
            require(head['selection'] == 'candidate' and head['decoder_kind'] == 'mixed'
                and head['enabled'] is enabled and head['selected_steps'] == stage['steps'] and head['checkpoint'] == stage['checkpoint'],
                    'selected checkpoint differs from independent temporal-first gate')
            for panel in TUNING_COUNTS:
                require(read_ref(stage['tuning_' + panel])['generation'] == read_ref(frozen['files'][name]['tuning_' + panel]),
                        'selected tuning differs from retained candidate')
        selected_audits = [row for row in exposure_audits if row['steps'] <= head['selected_steps']]
        audits.append({'name': name, 'curriculum': curriculum, 'architecture': settings['architecture'],
            'initial_full_model_sha256': digest(initial['model_state']), 'parent_tuning_exact': parent_scores,
            'stage_tuning': normalized, 'stage_exposure_audits': exposure_audits, 'baseline_stage_reproductions': reproductions,
            'selected_steps': head['selected_steps'], 'selection': head['selection'],
            'executed_domain_exposures': {'earlier': 4800, 'new': 4800},
            'selected_checkpoint_domain_exposures': {domain: 6 * head['selected_steps'] for domain in ('earlier', 'new')},
            'selected_checkpoint_new_subgroup_exposures': {group: sum(row['new_domain_subgroup_exposures'][group] for row in selected_audits)
                for group in ('prior_new', 'temporal_additions')},
            'fresh_adam_state_verified': True, 'initial_tensors_and_resumption_chain_verified': True,
            'optimizer_trajectory_replayed': False})
    require(baseline_reproductions == 12 and all(len(values) == 1 for values in common.values()),
            'all baseline reproductions or same-seed four-arm initial tensors differ')
    return jobs, audits


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_temporal_curriculum_experiment as runner
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(1 <= args.workers <= 3, 'one to three replay workers required')
    directory, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    frozen_ref = ref(directory / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == runner.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['challenge_targets_opened'] is False and frozen['regression_targets_opened'] is False
        and frozen['executed_optimizer_updates'] == 9600, 'complete source-only training/generation freeze required')
    plan = read_ref(frozen['plan'])
    require(plan['arms'] == ARMS and plan['seeds'] == list(SEEDS) and plan['stage_steps'] == 400 and plan['stages'] == 2
        and plan['retention_tolerance'] == 1 and plan['counts'] == PANEL_COUNTS
        and plan['domain_batch_sizes'] == {'earlier': 6, 'new': 6}
        and plan['training_domain_counts'] == {'baseline': {'earlier': 1152, 'new': 600}, 'temporal_augmented': {'earlier': 1152, 'new': 1200}}
        and plan['architecture_changed'] is plan['temporal_head_added'] is plan['loss_weights_changed'] is False
        and plan['baseline_exact_reproduction_required'] is True and plan['common_tuning_panels'] == list(TUNING_COUNTS)
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
    for module in (sys.modules[__name__], runner, prior, previous, calendar, calendar_summary, source_audit, gate):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    jobs, training_audits = verify_training(inputs, heads, frozen)
    training_ref = write(output / 'training-and-selection-audit.json', {'models': training_audits,
        'fitting_annotation_provenance': provenance, 'same_seed_initial_model_tensors_equal': True,
        'selected_stage_uses_tuning_only': True, 'optimizer_trajectory_replayed': False,
        'actual_optimizer_updates_recorded': 9600, 'recorded_training_exposures': {'earlier': 57600, 'new': 57600}, 'baseline_numeric_stage_reproductions': 12, **FALSE})
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
    require(sum(len(job['sources']) for job in jobs if job.get('stage')) == 7488
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
        'stage_tuning_rows': 7488, 'selected_model_rows': total_main_rows, 'training_audit': training_ref,
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
        require(value['source_count'] == len(value['rows']) + len(value['excluded']) == 180, 'fresh build selection dropped rows')
        selections[name] = value
    selected_ref = write(output / 'build-selection-frozen.json', {'models': selections, 'replay': replay_ref,
        'source_count': 2700, 'fresh_targets_opened': False, 'interpretation_policy': calendar.POLICY,
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
                   'exposed_regression': config['exposed_regression_targets'], 'mixed_regression': config['mixed_regression_targets']}
    references = {'tuning_' + panel: inputs['tuning'][panel] for panel in TUNING_COUNTS}
    for panel, reference in target_refs.items():
        references[panel] = previous.reference_rows(read_ref(reference), inputs['sources'][panel])
        for row in references[panel]:
            if 'canonical_target_sha256' in row:
                require(row['canonical_target_sha256'] == digest(row['canonical_ir']), 'posthoc reference canonical commitment differs')
    references['fresh_disabled'] = references['fresh']
    exposure = read_ref(manifest['artifacts']['exposure_audit'])
    require(all(exposure[key] == value for key, value in manifest.get('exposure_summary', {}).items()), 'surface-exposure summary differs from frozen audit')
    metrics, models = {}, []
    for item in items:
        name = item['name']; metrics[name] = {}
        for panel, generation in generations[name].items():
            sources = inputs['sources']['fresh' if panel == 'fresh_disabled' else panel]
            metrics[name][panel] = prior.annotated_metrics(generation, sources, references[panel],
                supervised_trigger=item['decoder_kind'] == 'mixed' and item['enabled'])
        exact = {r['id']: r['exact'] for r in metrics[name]['fresh']['rows']}
        controls = {}
        if 'fresh_disabled' in generations[name]:
            normal, disabled = generations[name]['fresh']['rows'], generations[name]['fresh_disabled']['rows']
            controls = {'count': 180, 'canonical_output_changed': sum((a['status'], a['canonical_ir']) != (b['status'], b['canonical_ir'])
                for a, b in zip(normal, disabled)),
                'recorded_prediction_changed': sum(a != b for a, b in zip(normal, disabled)),
                'normal_exact_minus_disabled': metrics[name]['fresh']['exact'] - metrics[name]['fresh_disabled']['exact']}
        models.append({'name': name, 'arm': item['arm'], 'seed': item['seed'], 'selection': item['selection'],
            'selected_steps': item['selected_steps'], 'executed_steps': item['executed_steps'], 'decoder_kind': item['decoder_kind'],
            'architecture': item['architecture'], 'curriculum': item['curriculum'],
            'checkpoint': item['checkpoint'], 'requested_enabled': item['requested_enabled'], 'enabled': item['enabled'],
            'metrics': {panel: {key: value for key, value in measured.items() if key != 'rows'} for panel, measured in metrics[name].items()},
            'builds': prior.build_accounting(selections[name], builds[name], exact), 'residual_controls': controls})
    paired = []
    for seed in SEEDS:
        pairs = [(f'temporal_augmented_{architecture}-{seed}', f'baseline_{architecture}-{seed}')
            for architecture in ('continuation', 'grounding')]
        pairs += [(f'{curriculum}_grounding-{seed}', f'{curriculum}_continuation-{seed}')
            for curriculum in ('baseline', 'temporal_augmented')]
        pairs += [(f'{arm}-{seed}', f'parent-{seed}') for arm in ARMS]
        for left, right in pairs:
            for panel in ('fresh', 'earlier_regression', 'exposed_regression', 'mixed_regression'):
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
                        ('checkpoint', 'training_report', 'tuning_earlier', 'tuning_prior_new', 'tuning_temporal')]]:
        read_ref(reference, parse=False)
    require(runner.load_config(plan['config']['path']) == inputs, 'fitting/source input closure changed during qualification')
    for reference in manifest['artifacts'].values():
        read_ref(reference, parse=False)
    result = {'schema': SCHEMA, 'generation_freeze': frozen_ref, 'training_selection_audit': training_ref,
        'replay': replay_ref, 'builds': build_ref, 'details': details_ref, 'producer_pins': pins,
        'models': models, 'totals': totals, 'paired_comparisons': paired,
        'replayed_rows': sum(r['rows'] for r in replays), 'retention_gate_failures': frozen['retention_gate_failures'],
        'executed_optimizer_updates': 9600, 'training_domain_exposures': {'earlier': 57600, 'new': 57600},
        'baseline_numeric_stage_reproductions': 12, 'architecture_and_loss_unchanged': True,
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes': True,
        'test_results_used_for_selection_or_gate_revision': False, 'unselected_candidate_test_scores_computed': False,
        'source_coordinate_provenance_verified': True, 'surface_exposure_audit': manifest['artifacts']['exposure_audit'],
        'surface_exposure_summary': manifest.get('exposure_summary'),
        'fresh_panel_scope': '180 newly authored examples in30 disjoint case groups; reference exposure and layout novelty claims remain bounded by the corpus audit',
        'regression_scopes': {'earlier_regression': '192 previously exposed authored examples',
                              'exposed_regression': '150 previously exposed grounding challenge examples',
                              'mixed_regression': '144 previously exposed mixed-replay challenge examples'},
        'scope': 'Matched architecture-by-curriculum comparison, temporal-first tuning after earlier retention, explicit parent fallback, and restricted source-copy/calendar validation; no full logic-family or statutory qualification',
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
