#!/usr/bin/env python3
"""Independent replay and native-build audit of boundary-only curriculum training.

All clause-decoder weights and boundary inference policy remain frozen. Fresh
reference and coordinate-derived layout evidence open after the build freeze.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import math
import multiprocessing
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_construction_retention_experiment as retained
from scripts.ops.legal_ir import analyze_legal_construction_segmentation as attribution
from scripts.ops.legal_ir import verify_legal_clause_boundary_experiment as boundary_audit
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary

require, digest, read_ref, ref, write, sha = retained.require, retained.digest, retained.read_ref, retained.ref, retained.write, retained.sha
SCHEMA = 'legal-boundary-curriculum-independent-qualification/v1'
SEEDS = (1729, 1730, 1731)
CURRICULA = ('replay_only', 'expanded')
POLICIES = ('parent', *CURRICULA)
ARCHITECTURES = ('continuation', 'grounding')
COUNTS = {'tuning_old': 48, 'tuning_new': 96, 'fresh_documents': 96,
          'prior_construction_documents': 96, 'exposed_documents': 96}
FALSE = retained.FALSE


def selection_choice(stages, parent_old_exact):
    """Closed tuning-only selection, independently expressed from the runner."""
    require(type(parent_old_exact) is int and 0 <= parent_old_exact <= 36,
            'bounded original tuning parent exact count required')
    require(type(stages) is list and [r.get('steps') for r in stages] == [200, 400, 600],
            'all three additional-update candidate stages required')
    bounds = {'old_exact': 36, 'old_decision_exact': 48, 'new_exact': 72, 'new_guard_accept': 24}
    for row in stages:
        require(set(row) == {'steps', *bounds} and
                all(type(row[k]) is int and 0 <= row[k] <= limit for k, limit in bounds.items()),
                'closed bounded tuning-only selection metrics required')
    eligible = [r for r in stages if r['old_exact'] >= parent_old_exact - 1 and r['new_guard_accept'] == 0]
    return max(eligible, key=lambda r: (r['new_exact'], r['old_decision_exact'], -r['steps'])) if eligible else None


def verify_inventory(models, heads, files, boundaries):
    expected_models = {f'{policy}_{architecture}-{seed}' for policy in POLICIES
                       for architecture in ARCHITECTURES for seed in SEEDS}
    expected_heads = {'parent'} | {f'{policy}-{seed}' for policy in CURRICULA for seed in SEEDS}
    require(len(models) == 18 and {m['name'] for m in models} == expected_models
        and len(heads) == 7 and {h['name'] for h in heads} == expected_heads
        and set(files) == expected_models and set(boundaries) == expected_heads,
        'complete eighteen pipeline slots and seven boundary heads required')
    head_by_name = {h['name']: h for h in heads}
    for model in models:
        policy, architecture, seed = model['boundary_policy'], model['architecture'], model['seed']
        name = f'{policy}_{architecture}-{seed}'
        wanted_head = 'parent' if policy == 'parent' else f'{policy}-{seed}'
        require(model['name'] == name and model['boundary_head'] == wanted_head
            and model['boundary_checkpoint'] == head_by_name[wanted_head]['checkpoint']
            and model['enabled'] is (architecture == 'grounding') and model['decoder_kind'] == 'mixed'
            and set(files[name]) == set(COUNTS), 'pipeline architecture, seed, head or panel binding differs')
    require(all(set(panels) == set(COUNTS) for panels in boundaries.values()), 'complete boundary panel inventory required')
    return {'pipeline_slots': 18, 'boundary_heads': 7,
            'selected_pipeline_source_rows': 18 * sum(COUNTS.values()),
            'selected_boundary_source_rows': 7 * sum(COUNTS.values())}


def score_boundaries(generation, sources, targets):
    require(len(generation['rows']) == len(sources) == len(targets), 'complete boundary score denominator required')
    predicted = {r['candidate_id']: r for r in generation['rows']}
    expected = {r['candidate_id']: r for r in targets}
    require(len(predicted) == len(expected) == len(sources) and set(predicted) == set(expected)
        == {r['candidate_id'] for r in sources}, 'unique complete boundary score identities required')
    # Logit thresholds, source offsets and complete source plans are audited in
    # addition to numerical replay. Reference order cannot silently change joins.
    ordered_predictions = {'rows': [predicted[s['candidate_id']] for s in sources]}
    ordered_targets = [expected[s['candidate_id']] for s in sources]
    legacy = boundary_audit.independent_counts(ordered_predictions, ordered_targets)
    rows = [attribution.boundary_record(source, predicted[source['candidate_id']], expected[source['candidate_id']])
            for source in sources]
    counts = attribution.boundary_counts(rows)
    require(counts['supported_delivered_interval_exact'] == legacy.get('exact_supported_segmentation', 0)
        and counts['unsupported_accepted_plan'] == legacy.get('unsupported_accepted', 0),
        'independent boundary metric contracts differ')
    return {**counts, 'rows': rows, 'legacy_counts': legacy}


def pipeline_funnel(generation, boundary_metrics, sources, targets, selection, batches):
    """Keep all failures, with compiler validity separate from reference fidelity."""
    metric = retained.score_documents(generation, sources, targets)
    boundary_rows = {r['id']: r for r in boundary_metrics['rows']}
    gold = {r['candidate_id']: r for r in targets}
    scored = [attribution.pipeline_record(row, gold[row['candidate_id']], boundary_rows[row['candidate_id']])
              for row in generation['rows']]
    attributed = attribution.pipeline_counts(scored)
    require(attributed['joint_exact'] == metric['exact'] and attributed['canonical_exact'] == metric['canonical_rule_list_exact'],
            'independent joint pipeline exact counts differ')
    chosen = [r['candidate']['candidate_id'] for r in selection['rows']]
    excluded = [r['candidate_id'] for r in selection['excluded']]
    ids = set(gold)
    require(len(chosen) + len(excluded) == len(ids) and len(set(chosen)) == len(chosen)
        and len(set(excluded)) == len(excluded) and set(chosen).isdisjoint(excluded)
        and set(chosen) | set(excluded) == ids, 'source-only build selection dropped or duplicated outcomes')
    require([i for batch in batches for i in batch['candidate_ids']] == chosen,
            'native build batches must preserve complete ordered build selection')
    built = {i for batch in batches if batch['build_passed'] for i in batch['candidate_ids']}
    generated = {r['candidate_id']: r for r in generation['rows']}
    exact = {r['id'] for r in metric['rows'] if r['exact']}
    canonical = {r['id'] for r in metric['rows'] if r['canonical_rule_list_exact']}
    stages = {}
    for identity in sorted(ids):
        row = generated[identity]
        if row['segmentation_status'] != 'segmented': stage = 'boundary_abstained'
        elif row['composition'] is None: stage = 'clause_decode_or_composition_abstained'
        elif identity not in chosen: stage = 'lowering_unsupported'
        elif identity not in built: stage = 'native_build_failed'
        elif identity in exact: stage = 'built_joint_exact'
        else: stage = 'built_reference_mismatch'
        stages[identity] = stage
    funnel = dict(Counter(stages.values()))
    require(sum(funnel.values()) == len(ids), 'pipeline stage funnel lost a document')
    for row in scored: row['terminal_stage'] = stages[row['id']]
    return {'metrics': {k: v for k, v in metric.items() if k != 'rows'},
        'attribution': attributed, 'rows': scored, 'terminal_stages': funnel,
        'builds': {'count': len(ids), 'supported_for_lowering': len(chosen), 'built': len(built),
            'built_exact': len(built & exact), 'built_canonical_only_exact': len(built & canonical),
            'built_reference_mismatch': len(built - exact), 'build_invocations': len(batches),
            'actual_lake_build_invocations': sum(b['backend_executed'] for b in batches)}}


def replay_job(job):
    import torch
    torch.set_num_threads(1)
    if job['kind'] == 'document':
        return retained.replay_job(job)
    expected = read_ref(job['generation'])
    if job.get('stage'): expected = expected['generation']
    actual = clauses.decode_all(boundary.ClauseBoundaryDecoder(read_ref(job['checkpoint'])), job['sources'])
    require(actual == expected, 'independent boundary output/logit replay differs: ' + job['name'])
    return {'kind': 'boundary', 'name': job['name'], 'checkpoint': job['checkpoint'],
        'generation': job['generation'], 'rows': len(job['sources']), 'source_inputs_sha256': digest(job['sources']),
        'recorded_generation_sha256': digest(actual), 'exact_recorded_payload_replay': True,
        'stage_tuning': job.get('stage', False), 'target_access': False}


def independent_schedule(replay, added, curriculum, seed):
    require(curriculum in CURRICULA and seed in SEEDS, 'declared schedule curriculum and seed required')
    rng = random.Random(seed)
    queues = {'old': [], 'new': []}
    pools = {'old': replay, 'new': added}
    result = []
    for step in range(1, 601):
        receipt = {'steps': step}
        for key, quota in (('old', 12 if curriculum == 'replay_only' else 6),
                           ('new', 0 if curriculum == 'replay_only' else 6)):
            batch = []
            for _ in range(quota):
                if not queues[key]:
                    order = list(range(len(pools[key]))); rng.shuffle(order)
                    queues[key] = [pools[key][i]['candidate_id'] for i in order]
                batch.append(queues[key].pop(0))
            receipt[key + '_ids'] = batch
        result.append(receipt)
    return result


def verify_training_contract(record, parent_ref, parent, replay, added, tuning):
    curriculum, seed = record['curriculum'], record['seed']
    require(curriculum in CURRICULA and seed in SEEDS and record['name'] == f'{curriculum}-{seed}',
            'declared curriculum/seed trial required')
    expected_train = {'curriculum': curriculum, 'original_replay_sha256': digest(replay),
        'new_train_sha256': digest(added) if curriculum == 'expanded' else None,
        'old_quota': 12 if curriculum == 'replay_only' else 6,
        'new_quota': 0 if curriculum == 'replay_only' else 6, 'sampler_seed': seed,
        'batch_size': 12, 'additional_optimizer_updates': 600,
        'sampler': 'shared_random.Random(seed); lazy_shuffle_range_at_pool_exhaustion; exact_quota_wraparound; old_then_new; no_batch_shuffle'}
    expected_tune = {k: digest(v) for k, v in tuning.items()}
    require(record['initial'] == parent_ref and parent['optimizer_steps'] == 200
        and record['initial_model_state_sha256'] == digest(parent['model_state'])
        and record['shared_pretrained_initialization'] is record['seed_controls_minibatch_order_only'] is True
        and record['independent_model_initializations'] is False, 'shared parent initialization commitment differs')
    require(record['training_manifest'] == expected_train and record['training_manifest_sha256'] == digest(expected_train)
        and record['tuning_manifest'] == expected_tune and record['tuning_manifest_sha256'] == digest(expected_tune),
        'fitting manifest or stream quotas differ')
    require(record['executed_optimizer_updates'] == len(record['losses']) == len(record['batches']) == 600
        and record['inherited_optimizer_steps'] == 200 and record['final_cumulative_optimizer_steps'] == 800
        and record['optimizer_reset'] is True and record['optimizer_resumption_supported'] is False
        and record['torch_threads'] == 1 and record['fresh_targets_opened'] is record['regression_targets_opened'] is False,
        'additional updates, inherited steps or optimizer reset contract differs')
    require(all(type(loss) in (float, int) and math.isfinite(loss) and loss >= 0 for loss in record['losses']),
            'finite nonnegative objective values required')
    require(len(record['training_step_seconds']) == 600 and all(type(t) in (float, int) and math.isfinite(t) and t >= 0
        for t in record['training_step_seconds']) and record['maximum_total_trial_seconds'] == 600
        and 0 <= record['optimizer_training_seconds'] <= record['elapsed_seconds_including_stage_tuning'] <= 600
        and math.isclose(sum(record['training_step_seconds']), record['optimizer_training_seconds'], rel_tol=1e-10),
        'bounded complete optimizer and wall-clock receipts required')
    expected_batches = independent_schedule(replay, added, curriculum, seed)
    require(record['batches'] == expected_batches and record['batch_schedule_sha256'] == digest(expected_batches),
            'independent complete optimizer batch schedule differs')
    require([s['steps'] for s in record['stages']] == [200, 400, 600], 'complete ordered checkpoint stages required')
    checks = []
    for stage in record['stages']:
        cp = read_ref(stage['checkpoint'])
        boundary.restore(cp)
        require(cp['optimizer_steps'] == stage['cumulative_optimizer_steps'] == 200 + stage['steps']
            and cp['training_manifest_sha256'] == digest(expected_train)
            and cp['tuning_manifest_sha256'] == digest(expected_tune), 'stage cumulative updates or fitting commitment differs')
        changed = sorted(k for k in parent['model_state'] if cp['model_state'][k] != parent['model_state'][k])
        require(bool(changed), 'continued fitting produced no changed model tensors')
        checks.append({'steps': stage['steps'], 'cumulative_optimizer_steps': cp['optimizer_steps'],
            'checkpoint': stage['checkpoint'], 'changed_parameter_names': changed})
    require(record['changed_parameter_names'] == checks[-1]['changed_parameter_names'], 'final changed tensor inventory differs')
    return {'name': record['name'], 'initial': parent_ref, 'training_manifest_sha256': digest(expected_train),
        'tuning_manifest_sha256': digest(expected_tune), 'batch_schedule_sha256': digest(expected_batches),
        'independent_batch_rows_verified': 7200, 'executed_optimizer_updates': 600, 'stages': checks,
        'shared_pretrained_initialization': True, 'seed_varies_minibatch_order_only': True,
        'optimizer_trajectory_replayed': False}


def verify_selection(inputs, frozen, heads, selection):
    require(selection['plan'] == frozen['plan'] and selection['executed_optimizer_updates'] == 3600
        and selection['fresh_targets_opened'] is selection['regression_targets_opened'] is False,
        'complete training-only selection freeze required')
    parent = read_ref(inputs['boundary_parent'])
    parent_fields = selection['parent_tuning']; jobs = []; parent_scores = {}
    for panel in ('old', 'new'):
        reference = parent_fields['tuning_' + panel]; saved = read_ref(reference)
        scored = score_boundaries(saved['generation'], inputs['sources']['tuning_' + panel], inputs['tuning'][panel])
        require(saved['metrics'] == clauses.evaluate(saved['generation'], inputs['tuning'][panel]), 'parent saved tuning metric payload differs')
        for key, metric in (('supported_exact', 'exact_supported_segmentation'), ('decision_exact', 'document_decision_exact'),
                            ('unsupported_accepted', 'unsupported_accepted')):
            require(parent_fields[panel + '_' + key] == scored['legacy_counts'].get(metric, 0), 'independent parent tuning count differs')
        parent_scores[panel] = scored
        require(saved['generation'] == read_ref(frozen['boundaries']['parent']['tuning_' + panel]), 'parent tuning/selected boundary outputs differ')
        jobs.append({'kind': 'boundary', 'name': 'parent-reference/tuning_' + panel, 'checkpoint': inputs['boundary_parent'],
            'generation': reference, 'sources': inputs['sources']['tuning_' + panel], 'stage': True})
    trials = selection['trials']; by_head = {h['name']: h for h in heads}; audits = []
    require(len(trials) == 6 and {(r['curriculum'], r['seed']) for r in trials} ==
        {(c, s) for c in CURRICULA for s in SEEDS}, 'all six curriculum training trials required')
    parent_exact = parent_scores['old']['supported_delivered_interval_exact']
    for trial in trials:
        record = read_ref(trial['training_report'])
        require({k: v for k, v in trial.items() if k != 'training_report'} == {k: record[k] for k in trial if k != 'training_report'},
                'training report differs from frozen selection inventory')
        require(record['parent_old_supported_exact'] == parent_exact, 'training parent retention anchor differs')
        training_audit = verify_training_contract(record, inputs['boundary_parent'], parent, inputs['replay'], inputs['new_train'], inputs['tuning'])
        normalized = []
        for stage in record['stages']:
            measured = {}
            for panel in ('old', 'new'):
                reference = stage['tuning_' + panel]; saved = read_ref(reference)
                scored = score_boundaries(saved['generation'], inputs['sources']['tuning_' + panel], inputs['tuning'][panel])
                require(saved['metrics'] == clauses.evaluate(saved['generation'], inputs['tuning'][panel]), 'stage saved metric payload differs')
                for key, metric in (('supported_exact', 'exact_supported_segmentation'), ('decision_exact', 'document_decision_exact'),
                                    ('unsupported_accepted', 'unsupported_accepted')):
                    value = scored['legacy_counts'].get(metric, 0)
                    require(stage[panel + '_' + key] == value, 'independent stage tuning count differs')
                    measured[panel + '_' + key] = value
                jobs.append({'kind': 'boundary', 'name': trial['name'] + f"/stage-{stage['steps']}/tuning_" + panel,
                    'checkpoint': stage['checkpoint'], 'generation': reference, 'sources': inputs['sources']['tuning_' + panel], 'stage': True})
            require(stage['eligible'] is (measured['old_supported_exact'] >= parent_exact - 1 and measured['new_unsupported_accepted'] == 0),
                    'recorded gate eligibility differs')
            normalized.append({'steps': stage['steps'], 'old_exact': measured['old_supported_exact'],
                'old_decision_exact': measured['old_decision_exact'], 'new_exact': measured['new_supported_exact'],
                'new_guard_accept': measured['new_unsupported_accepted']})
        chosen = selection_choice(normalized, parent_exact)
        wanted_steps = chosen['steps'] if chosen else 0
        wanted_checkpoint = next(s['checkpoint'] for s in record['stages'] if s['steps'] == wanted_steps) if chosen else inputs['boundary_parent']
        wanted_status = 'candidate' if chosen else 'parent_fallback_no_acceptable_replacement'
        require(record['selected_steps'] == wanted_steps and record['checkpoint'] == wanted_checkpoint and record['selection'] == wanted_status,
                'independent tuning-only checkpoint choice differs')
        head = by_head[trial['name']]
        require(head == {k: trial[k] for k in ('name', 'checkpoint', 'selection', 'selected_steps', 'curriculum', 'seed', 'training_report')},
                'selected boundary head differs from audited trial')
        audits.append({**training_audit, 'training_report': trial['training_report'], 'normalized_tuning_stages': normalized,
            'selected_steps': wanted_steps, 'checkpoint': wanted_checkpoint, 'selection': wanted_status,
            'acceptable_replacement_found': chosen is not None})
    require(by_head['parent'] == {'name': 'parent', 'checkpoint': inputs['boundary_parent'], 'selection': 'unchanged_parent', 'selected_steps': 0},
            'original boundary head changed')
    return jobs, audits, parent_scores


def verify_protocol(inputs, plan, frozen):
    require(plan['curricula'] == list(CURRICULA) and plan['seeds'] == list(SEEDS)
        and plan['additional_stage_steps'] == [200, 400, 600] and plan['source_counts'] == COUNTS
        and plan['boundary_parent'] == inputs['boundary_parent'] and plan['boundary_config'] == boundary.CONFIG
        and plan['shared_pretrained_initialization'] is plan['seed_controls_minibatch_order_only'] is True
        and plan['optimizer_reset'] is True and plan['optimizer_resumption_supported'] is False
        and plan['batch_quotas'] == {'replay_only': {'old': 12, 'new': 0}, 'expanded': {'old': 6, 'new': 6}}
        and plan['loss'] == {'boundary_positive_weight': 12., 'scope_class_weights': [3., 1.], 'gradient_clip_norm': 5.}
        and plan['old_supported_retention_tolerance'] == 1 and plan['new_guard_false_acceptance_tolerance'] == 0
        and plan['threads_per_worker'] == 1 and 1 <= plan['workers'] <= 3
        and plan['maximum_total_trial_seconds'] == 600
        and plan['fresh_targets_opened'] is plan['regression_targets_opened'] is False,
        'predeclared boundary-only training protocol differs')
    design = read_ref(inputs['config']['study_design'])
    require(design['status'] == 'preregistered_before_training_or_new_tuning_inference'
        and design['parent_boundary_checkpoint'] == inputs['boundary_parent'] and design['seeds'] == list(SEEDS)
        and design['training']['total_new_optimizer_updates_if_completed'] == 3600
        and design['training']['stage_additional_steps'] == [200, 400, 600]
        and design['training']['batch_quotas'] == {'replay_only': {'original_boundary_train': 12, 'new_train': 0},
            'expanded': {'original_boundary_train': 6, 'new_train': 6}}
        and design['selection']['rank_eligible'] == ['new_tuning supported accepted interval exact descending',
            'old_tuning document decision exact descending', 'additional training steps ascending'],
        'frozen pretraining study design differs')
    for model in frozen['models']:
        control = inputs['clause_controls'][(model['architecture'], model['seed'])]
        require(model['checkpoint'] == control['checkpoint'] and model['clause_source_model'] == control['name']
            and model['clause_curriculum'] == 'temporal_augmented' and model['clause_selected_steps'] == 800
            and model['clause_optimizer_updates'] == 0 and model['arm'] == model['boundary_policy'] + '_' + model['architecture'],
            'frozen temporal800 clause architecture or checkpoint changed')
    return design


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as corpus
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1 <= args.workers <= 3, 'one to three independent CPU replay workers required')
    folder, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    frozen_ref = ref(folder / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == runner.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['fresh_targets_opened'] is frozen['regression_targets_opened'] is False
        and frozen['executed_optimizer_updates'] == 3600 and frozen['clause_optimizer_updates'] == 0
        and frozen['training_executed'] is True, 'complete source-only boundary training and pipeline freeze required')
    plan = read_ref(frozen['plan'])
    require(all(sha(path) == wanted for path, wanted in plan['producer_pins'].items()), 'frozen training/generation producer drift')
    read_ref(plan['config'], parse=False); inputs = runner.load_config(plan['config']['path'])
    require(read_ref(frozen['sources']) == inputs['sources'] and read_ref(frozen['heads']) == frozen['models'],
            'frozen source or model inventory differs')
    heads = read_ref(frozen['boundary_heads'])
    inventory = verify_inventory(frozen['models'], heads, frozen['document_files'], frozen['boundaries'])
    verify_protocol(inputs, plan, frozen)
    output.mkdir(parents=True, exist_ok=False)
    pins = dict(plan['producer_pins'])
    for module in (sys.modules[__name__], runner, corpus, retained, attribution, boundary_audit, clauses, boundary,
                   retained.prior, retained.calendar, retained.calendar_summary, retained.compose, gate):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    selection = read_ref(frozen['selections'])
    jobs, selection_audits, parent_scores = verify_selection(inputs, frozen, heads, selection)
    require(frozen['parent_fallbacks'] == [r['name'] for r in selection['trials'] if r['selection'] != 'candidate'],
            'parent fallback inventory differs')
    selection_ref = write(output / 'selection-audit.json', {'schema': SCHEMA, 'selection_freeze': frozen['selections'],
        'trials': selection_audits, 'parent_tuning': parent_scores, 'executed_optimizer_updates': 3600,
        'parent_fallback_means_no_acceptable_replacement': True, **FALSE})
    for head in heads:
        for panel, reference in frozen['boundaries'][head['name']].items():
            jobs.append({'kind': 'boundary', 'name': head['name'] + '/' + panel, 'checkpoint': head['checkpoint'],
                'generation': reference, 'sources': inputs['sources'][panel]})
    documents = {}
    for model in frozen['models']:
        name = model['name']; documents[name] = {}
        head = next(h for h in heads if h['name'] == model['boundary_head'])
        require(model['boundary_selected_steps'] == head['selected_steps'] and model['boundary_selection'] == head['selection'],
                'pipeline selected boundary attribution differs')
        for panel, reference in frozen['document_files'][name].items():
            documents[name][panel] = read_ref(reference)
            require(len(documents[name][panel]['rows']) == COUNTS[panel], 'pipeline inference dropped source documents')
            jobs.append({'kind': 'document', 'name': name + '/' + panel, 'model': model, 'generation': reference,
                'sources': inputs['sources'][panel], 'boundary': frozen['boundaries'][model['boundary_head']][panel]})
    require(sum(len(j['sources']) for j in jobs if j['kind'] == 'boundary' and j.get('stage')) == 2736
        and sum(len(j['sources']) for j in jobs if j['kind'] == 'boundary' and not j.get('stage')) == 3024
        and sum(len(j['sources']) for j in jobs if j['kind'] == 'document') == 7776,
        'complete parent/stage/selected boundary and pipeline replay denominators differ')
    replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(replay_job, job) for job in jobs]):
            value = future.result(); replays.append(value)
            print({'phase': 'replayed', 'kind': value['kind'], 'panel': value['name'], 'rows': value['rows']}, flush=True)
    for i, left in enumerate(heads):
        for right in heads[i + 1:]:
            if left['checkpoint'] == right['checkpoint']:
                require(all(read_ref(frozen['boundaries'][left['name']][p]) == read_ref(frozen['boundaries'][right['name']][p]) for p in COUNTS),
                        'duplicate boundary checkpoint slots differ')
    for i, left in enumerate(frozen['models']):
        for right in frozen['models'][i + 1:]:
            if left['checkpoint'] == right['checkpoint'] and left['boundary_checkpoint'] == right['boundary_checkpoint']:
                require(documents[left['name']] == documents[right['name']], 'duplicate full pipeline checkpoint slots differ')
    replay_ref = write(output / 'replay-frozen.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'selection_audit': selection_ref, 'panels': sorted(replays, key=lambda r: r['name']),
        'boundary_source_rows': 5760, 'pipeline_source_rows': 7776,
        'clause_occurrences_replayed': sum(r.get('clause_occurrences_replayed', 0) for r in replays),
        'fresh_and_regression_targets_opened': False, **FALSE})
    selections = {model['name']: retained.document_selection(documents[model['name']]['fresh_documents']['rows'],
        inputs['sources']['fresh_documents'], toolchain=args.toolchain) for model in frozen['models']}
    build_selection_ref = write(output / 'build-selection-frozen.json', {'schema': SCHEMA, 'models': selections,
        'replay': replay_ref, 'source_slots': 1728, 'fresh_targets_opened': False,
        'canonical_references_used_for_selection': False, 'interpretation_policy': retained.calendar.POLICY})
    builds = {}
    for model in frozen['models']:
        name = model['name']
        builds[name] = retained.build_batches(selections[name]['rows'], output / 'builds' / name, args)
        print({'phase': 'built', 'model': name, 'supported_for_lowering': len(selections[name]['rows'])}, flush=True)
    builds_ref = write(output / 'builds-frozen.json', {'schema': SCHEMA, 'models': builds,
        'selections': build_selection_ref, 'replay': replay_ref, 'fresh_and_regression_targets_opened': False, **FALSE})
    # The first fresh/regression label and role-coordinate evidence access occurs here.
    target_refs = {'fresh_documents': inputs['manifest']['artifacts']['fresh_targets'],
        'prior_construction_documents': inputs['config']['prior_construction_targets'],
        'exposed_documents': inputs['config']['exposed_document_targets']}
    targets = {'tuning_old': inputs['tuning']['old'], 'tuning_new': inputs['tuning']['new']}
    for panel, reference in target_refs.items():
        targets[panel] = read_ref(reference)
        require(clauses.source_rows(targets[panel]) == inputs['sources'][panel], 'post-build document source/reference binding differs')
    evidence_refs = {key: inputs['manifest']['artifacts'][key] for key in ('annotation_ledger', 'exposure_audit')}
    evidence = {key: read_ref(reference) for key, reference in evidence_refs.items()}
    exposure = audit_exposure(inputs, targets, evidence)
    exposure_ref = write(output / 'construction-exposure-audit.json', exposure)
    boundary_metrics = {}
    for head in heads:
        boundary_metrics[head['name']] = {}
        for panel in COUNTS:
            generation = read_ref(frozen['boundaries'][head['name']][panel])
            boundary_metrics[head['name']][panel] = score_boundaries(generation, inputs['sources'][panel], targets[panel])
    scored, reports = {}, []
    for model in frozen['models']:
        name = model['name']; scored[name] = {}
        for panel in COUNTS:
            if panel == 'fresh_documents':
                chosen, native = selections[name], builds[name]
            if panel == 'fresh_documents':
                scored[name][panel] = pipeline_funnel(documents[name][panel], boundary_metrics[model['boundary_head']][panel],
                    inputs['sources'][panel], targets[panel], chosen, native)
            else:
                metric = retained.score_documents(documents[name][panel], inputs['sources'][panel], targets[panel])
                gold = {r['candidate_id']: r for r in targets[panel]}
                b = {r['id']: r for r in boundary_metrics[model['boundary_head']][panel]['rows']}
                rows = [attribution.pipeline_record(r, gold[r['candidate_id']], b[r['candidate_id']]) for r in documents[name][panel]['rows']]
                scored[name][panel] = {'metrics': {k: v for k, v in metric.items() if k != 'rows'},
                    'rows': rows, 'attribution': attribution.pipeline_counts(rows), 'native_build_not_executed_on_this_panel': True}
        reports.append({**model, 'panels': {p: {k: v for k, v in m.items() if k != 'rows'} for p, m in scored[name].items()}})
    totals = {}
    for policy in POLICIES:
        for architecture in ARCHITECTURES:
            arm = policy + '_' + architecture; group = [r for r in reports if r['arm'] == arm]
            totals[arm] = {}
            for panel in COUNTS:
                keys = ('count', 'supported', 'unsupported', 'composed', 'abstained', 'exact', 'decision_exact',
                    'canonical_rule_list_exact', 'occurrence_boundaries_exact', 'unsupported_accepted')
                totals[arm][panel] = {k: sum(r['panels'][panel]['metrics'][k] for r in group) for k in keys}
                if panel == 'fresh_documents':
                    totals[arm][panel]['builds'] = {k: sum(r['panels'][panel]['builds'][k] for r in group)
                        for k in group[0]['panels'][panel]['builds']}
                    totals[arm][panel]['terminal_stages'] = dict(sum((Counter(r['panels'][panel]['terminal_stages']) for r in group), Counter()))
    paired = []
    for seed in SEEDS:
        for architecture in ARCHITECTURES:
            for left_policy, right_policy in (('replay_only', 'parent'), ('expanded', 'parent'), ('expanded', 'replay_only')):
                left, right = f'{left_policy}_{architecture}-{seed}', f'{right_policy}_{architecture}-{seed}'
                for panel in COUNTS:
                    a = {r['id']: r['joint_exact'] for r in scored[left][panel]['rows']}
                    b = {r['id']: r['joint_exact'] for r in scored[right][panel]['rows']}
                    require(set(a) == set(b), 'paired pipeline identities differ')
                    paired.append({'panel': panel, 'left': left, 'right': right, 'count': len(a),
                        'left_only_exact': sum(a[i] and not b[i] for i in a), 'right_only_exact': sum(b[i] and not a[i] for i in a),
                        'both_exact': sum(a[i] and b[i] for i in a)})
    details_ref = write(output / 'scored-details.json', {'boundary': boundary_metrics, 'pipeline': scored})
    require(all(sha(path) == wanted for path, wanted in pins.items()), 'qualifier or frozen producer drift')
    require(runner.load_config(plan['config']['path']) == inputs, 'frozen training/source input closure changed')
    for reference in [frozen_ref, frozen['plan'], frozen['sources'], frozen['heads'], frozen['boundary_heads'], frozen['selections'],
        *target_refs.values(), *evidence_refs.values(), *[r for panels in frozen['boundaries'].values() for r in panels.values()],
        *[r for panels in frozen['document_files'].values() for r in panels.values()]]:
        read_ref(reference, parse=False)
    result = {'schema': SCHEMA, 'generation_freeze': frozen_ref, 'selection_audit': selection_ref, 'replay': replay_ref,
        'builds': builds_ref, 'details': details_ref, 'construction_exposure_audit': exposure_ref,
        'reference_documents': target_refs, 'posthoc_evidence': evidence_refs, 'models': reports, 'totals': totals,
        'paired_comparisons': paired, 'producer_pins': pins, 'parent_fallbacks': frozen['parent_fallbacks'],
        'boundary_heads': [{**head, 'panels': {p: {k: v for k, v in m.items() if k not in ('rows', 'legacy_counts')}
            for p, m in boundary_metrics[head['name']].items()}} for head in heads],
        'executed_optimizer_updates': 3600, 'clause_optimizer_updates': 0, 'new_checkpoint_training_performed': True,
        'boundary_source_documents_replayed': 5760, 'pipeline_document_inference_rows_replayed': 7776,
        'clause_occurrences_replayed': sum(r.get('clause_occurrences_replayed', 0) for r in replays),
        'actual_lake_build_invocations': sum(b['backend_executed'] for batches in builds.values() for b in batches),
        'build_attempts': sum(len(batches) for batches in builds.values()), 'inventory': inventory,
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes': True,
        'reference_derived_novelty_evidence_opened_after_build_freeze': True,
        'test_results_used_for_selection_or_gate_revision': False,
        'independent_model_initializations': False, 'seed_scope': 'Minibatch orders from the same frozen parent; paired same-seed clause decoder',
        'scope': 'Boundary-only continuation, authored restricted flat source-copy/calendar cases; no statutory correctness or universal construction novelty claim',
        **FALSE}
    write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'totals': totals}, flush=True)
    return result


def audit_exposure(inputs, targets, evidence):
    """Reconstruct all compared local layouts after native build commitments."""
    from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as corpus
    exposure, ledger = evidence['exposure_audit'], evidence['annotation_ledger']
    require(exposure['schema'] == 'legal-boundary-curriculum-exposure/v1'
        and ledger['schema'] == 'legal-boundary-curriculum-annotations/v1', 'posthoc exposure schema differs')
    pm = read_ref(inputs['manifest']['inputs']['previous_corpus'])
    expected_refs = corpus.known_pool_references(pm)
    for key, artifact in (('new_boundary_training_clauses', 'new_training_targets'), ('new_boundary_tuning_clauses', 'tuning_targets')):
        expected_refs[key] = {'reference': inputs['manifest']['artifacts'][artifact], 'representation': 'document_clauses'}
    require(exposure['known_pool_references'] == expected_refs, 'known exposure inputs changed from pinned manifest ancestry')
    pools = {}
    for name, metadata in expected_refs.items():
        rows = read_ref(metadata['reference']); representation = metadata['representation']
        if representation == 'document_clauses': rows = retained.document_audit_clauses(rows)
        elif representation == 'earlier_single_targets':
            sources = {r['id']: r for r in read_ref(metadata['source_reference'])['splits']['challenge']}
            converted = []
            for row in rows['targets']:
                fields = {}
                for field in ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal'):
                    value = row['source_spans'][field]
                    fields[field] = (value[0] if value else None) if field in ('conditions', 'exceptions', 'temporal') else (value or None)
                converted.append({'id': row['id'], 'source_text': sources[row['id']]['source_text'], 'facet_spans': fields})
            rows = converted
        else:
            require(representation in ('annotated_single', 'grounding_single'), 'closed known-pool representation required')
        if 'filter_domain' in metadata: rows = [r for r in rows if r['domain'] == metadata['filter_domain']]
        pools[name] = rows
    layouts = {name: {retained.independent_layout(row) for row in rows} for name, rows in pools.items()}
    require(exposure['known_pool_counts'] == {k: len(v) for k, v in pools.items()}
        and exposure['known_role_masked_layouts'] == {k: sorted(v) for k, v in layouts.items()},
        'independent local exposure layouts or pool denominators differ')
    panels = {'train': inputs['new_train'], 'tuning': inputs['tuning']['new'], 'fresh': targets['fresh_documents']}
    annotations = {r['candidate_id']: r for r in ledger['document_rows']}
    require(len(annotations) == len(ledger['document_rows']) == 576
        and set(annotations) == {r['candidate_id'] for rows in panels.values() for r in rows}, 'complete new annotation inventory required')
    seen_groups = set(); family_occurrences = Counter(); facet_presence = Counter()
    for panel, rows in panels.items():
        for row in rows:
            annotation = annotations[row['candidate_id']]
            require(annotation['panel'] == panel and annotation['source_sha256'] == row['source_sha256'] == boundary.text_sha(row['source_text'])
                and annotation['supported'] is row['supported'] and annotation['guard'] == row['unsupported_reason']
                and annotation['case_group'] not in seen_groups, 'unique document case/source/support annotation binding differs')
            seen_groups.add(annotation['case_group'])
            coords = annotation['clause_coordinates']
            require(len(coords) == len(row['clauses']), 'complete occurrence coordinate inventory required')
            for index, (coord, clause) in enumerate(zip(coords, row['clauses'])):
                require(coord['clause_index'] == index and coord['char_start'] == clause['char_start'] and coord['char_end'] == clause['char_end']
                    and coord['family'] == annotation['family'] == row['construction'], 'authored clause coordinate or family differs')
                for field in ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal'):
                    value = clause['rule'][field]
                    atom = (value[0] if value else None) if field in ('conditions', 'exceptions', 'temporal') else value
                    span = coord['facet_spans'][field]
                    require((span is None) is (atom is None), 'present/absent authored coordinate differs')
                    if span is not None:
                        require(len(span) == 2 and all(type(x) is int for x in span)
                            and clause['char_start'] <= span[0] < span[1] <= clause['char_end']
                            and row['source_text'][span[0]:span[1]] == atom, 'authored facet source occurrence differs')
                    if panel == 'fresh' and field in ('conditions', 'exceptions', 'temporal'):
                        facet_presence[field + ('_present' if atom is not None else '_absent')] += 1
                if panel == 'fresh': family_occurrences[annotation['family']] += 1
    fresh = retained.document_audit_clauses(targets['fresh_documents'])
    expected_evidence = []
    for row in fresh:
        shape = retained.independent_layout(row)
        matches = sorted(name for name, shapes in layouts.items() if shape in shapes)
        require(matches == [], 'fresh supported clause repeats a pinned known local layout')
        expected_evidence.append({'id': row['id'], 'source_sha256': boundary.text_sha(row['source_text']),
            'role_masked_layout': shape, 'matching_pools': matches})
    require(exposure['fresh_clause_evidence'] == expected_evidence and len(fresh) == 180
        and set(family_occurrences) == set(inputs['manifest']['fresh_families']) and len(family_occurrences) == 6,
        'complete six-family fresh occurrence exposure evidence differs')
    require(all(facet_presence[f + '_absent'] == 60 and facet_presence[f + '_present'] == 120
        for f in ('conditions', 'exceptions', 'temporal')), 'balanced fresh present/absent qualifier counts differ')
    return {'known_pool_references': expected_refs, 'known_pool_counts': {k: len(v) for k, v in pools.items()},
        'fresh_supported_clause_occurrences': len(fresh), 'fresh_family_occurrences': dict(family_occurrences),
        'fresh_facet_presence': dict(facet_presence), 'new_annotation_documents_verified': 576,
        'fresh_clause_matches_in_compared_pools': 0, 'local_masked_layout_holdout_verified': True,
        'universal_language_or_pretraining_novelty_claimed': False, 'guard_wrapper_novelty_claimed': False,
        'scope': 'Six authored qualifier-position combinations versus the explicitly pinned local exposure inventory.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--lake-executable', required=True); parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    parser.add_argument('--workers', type=int, default=3)
    run(parser.parse_args())
