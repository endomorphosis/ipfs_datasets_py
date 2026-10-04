#!/usr/bin/env python3
"""Independent audit of selection-only construction/document retention.

All checkpoints already exist. Source-parent single-rule retention and a matched
baseline800 document floor are verified independently before fresh evaluation.
Every fresh build freezes before any fresh single/document reference is opened.
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
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from scripts.ops.legal_ir import transfer_learned_legal_clause_pipeline as transfer
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as compose

require, digest, read_ref, ref, write, sha = prior.require, prior.digest, prior.read_ref, prior.ref, prior.write, prior.sha
SCHEMA = 'legal-construction-retention-independent-qualification/v1'
SEEDS = prior.SEEDS
ARMS = ('prior_continuation', 'prior_grounding', 'document_retained_continuation', 'document_retained_grounding')
TUNING_COUNTS = {'earlier': 96, 'prior_new': 96, 'temporal': 120}
SINGLE_COUNTS = {'tuning_earlier': 96, 'tuning_prior_new': 96, 'tuning_temporal': 120,
    'fresh': 180, 'seen_layout_anchor': 30, 'earlier_regression': 192, 'exposed_regression': 150, 'mixed_regression': 144, 'temporal_regression': 180}
DOCUMENT_COUNTS = {'document_tuning': 96, 'fresh_documents': 96, 'exposed_documents': 96}
FALSE = prior.FALSE


def retention_choice(stages, source_parent_earlier, baseline_document_exact, baseline_earlier):
    require(type(source_parent_earlier) is int and 0 <= source_parent_earlier <= 96
        and type(baseline_document_exact) is int and 0 <= baseline_document_exact <= 72
        and type(baseline_earlier) is int and 0 <= baseline_earlier <= 96, 'bounded independent retention references required')
    require(baseline_earlier >= source_parent_earlier - 1, 'baseline fallback violates source-parent single-rule retention')
    require(type(stages) is list and len(stages) == 2 and [r['steps'] for r in stages] == [400, 800],
            'both existing400/800 candidate stages required')
    bounds = {'earlier_exact': 96, 'prior_new_exact': 96, 'temporal_exact': 120, 'document_exact': 72}
    for row in stages:
        require(set(row) == {'steps', *bounds} and all(type(row[k]) is int and 0 <= row[k] <= bound for k, bound in bounds.items()),
                'closed tuning-only stage metrics required')
    eligible = [row for row in stages if row['earlier_exact'] >= source_parent_earlier - 1
                and row['document_exact'] >= baseline_document_exact - 1]
    return max(eligible, key=lambda row: (row['temporal_exact'], row['document_exact'], row['prior_new_exact'],
                                         row['earlier_exact'], -row['steps'])) if eligible else None


def verify_panel_inventory(items, single_files, document_files):
    expected = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS} | {f'parent-{seed}' for seed in SEEDS}
    require(len(items) == 15 and {row['name'] for row in items} == expected
        and set(single_files) == set(document_files) == expected, 'all15 retained/control/parent slots required')
    single_rows = 0
    for item in items:
        panels = set(SINGLE_COUNTS)
        if item['enabled']:
            require(item['decoder_kind'] == 'mixed', 'enabled residual requires mixed decoder kind')
            panels.add('fresh_disabled')
        require(set(single_files[item['name']]) == panels and set(document_files[item['name']]) == set(DOCUMENT_COUNTS),
                'complete selected single/document panel inventory required')
        single_rows += sum(180 if p == 'fresh_disabled' else SINGLE_COUNTS[p] for p in panels)
    require(single_rows == 18900, 'all six grounding control panels required even for baseline fallback')
    return {'single_rows': single_rows, 'document_rows': 4320, 'model_slots': 15}


def document_selection(records, sources, *, toolchain):
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(len(records) == len(sources) == 96 and {r['candidate_id'] for r in records} == {s['candidate_id'] for s in sources},
            'complete unique document source inventory required')
    by_id = {source['candidate_id']: source for source in sources}
    require(len(by_id) == 96, 'unique document source identities required')
    entries, excluded = [], []
    for record in records:
        source = by_id[record['candidate_id']]
        require(record['source_sha256'] == source['source_sha256'], 'document prediction/source commitment differs')
        if record['composition'] is None:
            excluded.append({'candidate_id': record['candidate_id'], 'reason': record['reason'], 'status': record['status']})
            continue
        value = record['composition']; plan_hash = value['source_plan_sha256']
        require(value['source_plan']['source'] == source, 'composition source plan differs from original document')
        candidate = compose.calendar_candidate(value, expected_plan_sha256=plan_hash)
        try:
            interpretation = calendar.synthetic_interpretation(candidate, policy=calendar.POLICY)
            require(interpretation == calendar_summary.expected_interpretation(candidate), 'independent calendar policy differs')
            compose.prepare_calendar_composition(value, interpretation, expected_plan_sha256=plan_hash)
            entry = {'candidate': candidate, 'interpretation': interpretation}
            require(gate.prepare_qualified_legal([entry], toolchain=toolchain).to_dict()['all_candidates_supported'], 'unsupported calendar candidate')
            entries.append(entry)
        except (ValueError, KeyError, TypeError) as error:
            excluded.append({'candidate_id': record['candidate_id'], 'reason': str(error), 'status': 'interpretation_unsupported'})
    require(len(entries) + len(excluded) == 96, 'document selection dropped a source')
    return {'rows': entries, 'excluded': excluded, 'source_count': 96}


def score_documents(generation, sources, references):
    """Preserve split/merge and unsupported-acceptance errors as scored outcomes."""
    records = generation['rows']
    expected = {row['candidate_id']: row for row in references}
    require(len(records) == len(sources) == len(references) and len(expected) == len(references)
        and {r['candidate_id'] for r in records} == {s['candidate_id'] for s in sources} == set(expected),
            'complete unique document scoring denominator required')
    source_by_id = {s['candidate_id']: s for s in sources}
    counts = dict(count=0, supported=0, exact=0, decision_exact=0, composed=0, abstained=0,
                  unsupported=0, unsupported_accepted=0, canonical_rule_list_exact=0, occurrence_boundaries_exact=0)
    details = []
    for record in records:
        identity = record['candidate_id']; source = source_by_id[identity]; target = expected[identity]
        require(record['source_sha256'] == target['source_sha256'] == source['source_sha256'], 'document target/source differs')
        require(type(target['supported']) is bool and record['status'] in ('composed', 'abstained'), 'document status or support profile differs')
        supported = target['supported']; value = record['composition']
        require((record['status'] == 'composed') is (value is not None), 'document status/composition differs')
        actual = None if value is None else value['source_rule_list']
        wanted = [row['rule'] for row in target['clauses']] if supported else None
        accepted = value is not None
        canonical_exact = bool(supported and accepted and actual == wanted)
        actual_intervals = [(clause.get('char_start'), clause.get('char_end')) for clause in
            value.get('source_plan', {}).get('clauses', [])] if accepted else []
        target_intervals = [(clause['char_start'], clause['char_end']) for clause in target['clauses']] if supported else []
        boundaries_exact = bool(supported and accepted and actual_intervals == target_intervals)
        exact = canonical_exact and boundaries_exact
        counts['count'] += 1; counts['supported'] += supported; counts['unsupported'] += not supported
        counts['composed'] += accepted; counts['abstained'] += not accepted
        counts['canonical_rule_list_exact'] += canonical_exact; counts['occurrence_boundaries_exact'] += boundaries_exact
        counts['exact'] += exact; counts['decision_exact'] += exact or (not supported and not accepted)
        counts['unsupported_accepted'] += not supported and accepted
        details.append({'id': identity, 'supported': supported, 'exact': exact,
            'decision_exact': exact or (not supported and not accepted), 'canonical_rule_list_exact': canonical_exact,
            'occurrence_boundaries_exact': boundaries_exact, 'composed': accepted,
            'segmentation_status': record['segmentation_status'],
            'predicted_rule_count': len(actual) if accepted else None,
            'reference_rule_count': len(wanted) if supported else None})
    require(counts['count'] == counts['composed'] + counts['abstained'] == counts['supported'] + counts['unsupported'],
            'document score accounting differs')
    return {**counts, 'rows': details, 'wrong_boundaries_or_rule_counts_retained_as_errors': True}


def replay_job(job):
    if job['kind'] == 'single':
        return {**prior.replay_job(job), 'kind': 'single'}
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_construction_retention_experiment as runner
    boundary_generation = read_ref(job['boundary'])
    item = job['model']
    actual = runner.generate_documents(runner.load_decoder(item['checkpoint'], item['decoder_kind']), boundary_generation, job['sources'])
    expected = read_ref(job['generation'])
    if job.get('stage'): expected = expected['generation']
    require(actual == expected, 'fresh document/clause/composition numerical replay differs: ' + job['name'])
    by_id = {row['candidate_id']: row for row in boundary_generation['rows']}
    sources = {row['candidate_id']: row for row in job['sources']}
    clause_count = copied = composed = 0
    require(len(actual['rows']) == len(sources) and {r['candidate_id'] for r in actual['rows']} == set(sources), 'document replay source coverage differs')
    for row in actual['rows']:
        source = sources[row['candidate_id']]; segment = by_id[row['candidate_id']]
        require(row['source_sha256'] == source['source_sha256'] and row['segmentation_status'] == segment['status'], 'document/source/boundary binding differs')
        plan = segment['plan']
        if plan is None:
            require(row['clause_generation'] is row['composition'] is None and row['status'] == 'abstained', 'abstained boundary emitted clauses')
        else:
            require(plan['source'] == source, 'learned clause plan source differs')
            compose.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
            report = row['clause_generation']
            require(len(report['rows']) == plan['clause_count'], 'clause occurrence inventory differs')
            for clause, prediction in zip(plan['clauses'], report['rows']):
                copied += prior.source_audit.assert_source_copy(prediction, clause)
                clause_count += 1
            if row['composition'] is not None:
                value = row['composition']
                require(value['source_plan'] == plan, 'composition changed learned boundaries')
                compose.validate_composition(value, expected_plan_sha256=plan['plan_sha256'])
                composed += 1
    return {'kind': 'document', 'name': job['name'], 'rows': len(job['sources']), 'generation': job['generation'],
        'checkpoint': item['checkpoint'], 'boundary': job['boundary'], 'source_inputs_sha256': digest(job['sources']),
        'recorded_generation_sha256': digest(actual), 'exact_recorded_payload_replay': True,
        'clause_occurrences_replayed': clause_count, 'copied_facets_verified': copied, 'composed_documents': composed,
        'target_access': False, 'stage_tuning': job.get('stage', False)}


def verify_selection(inputs, frozen, selection):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    require(selection['executed_optimizer_updates'] == 0 and selection['training_executed'] is False
        and selection['fresh_targets_opened'] is selection['regression_targets_opened'] is False
        and selection['boundaries'] == frozen['boundaries'] and selection['plan'] == frozen['plan'], 'selection-only freeze differs')
    trials = selection['trials']
    require(len(trials) == 6 and {(r['architecture'], r['seed']) for r in trials} == {
        (architecture, seed) for architecture in ('continuation', 'grounding') for seed in SEEDS}, 'complete six selection trials required')
    models = {r['name']: r for r in frozen['models']}
    jobs, audits, parent_exact, parent_digests = [], [], {}, {}
    for seed in SEEDS:
        item = models[f'parent-{seed}']; historical_parent = inputs['parents'][seed]
        require(item['checkpoint'] == historical_parent['checkpoint'] and item['decoder_kind'] == 'parent'
            and item['arm'] == item['curriculum'] == item['architecture'] == 'parent'
            and item['selection'] == 'unchanged_parent' and item['enabled'] is item['requested_enabled'] is False
            and item['selected_steps'] == item['new_optimizer_steps'] == 0, 'original source parent slot differs')
        cp = dimensions.load_checkpoint(item['checkpoint']['path'], expected_sha256=item['checkpoint']['sha256'])
        require(cp['config']['seed'] == seed and cp['config']['latent_dimension'] == 0, 'original same-seed source-only parent required')
        parent_digests[seed] = digest(cp)
        scores = {}
        for panel in TUNING_COUNTS:
            reference = selection['parent_tuning'][str(seed)][panel]; payload = read_ref(reference)
            sources = inputs['sources']['tuning_' + panel]
            measured = previous.score(payload['generation']['rows'], sources, inputs['tuning'][panel])
            require(payload['metrics'] == measured and payload['generation'] == read_ref(frozen['files'][item['name']]['tuning_' + panel])
                == read_ref(inputs['historical']['files'][item['name']]['tuning_' + panel]), 'parent single tuning replay/score differs')
            scores[panel] = measured['exact']
            jobs.append({'kind': 'single', 'name': f"parent-reference-{seed}/tuning_{panel}", 'model': item,
                'generation': reference, 'sources': sources, 'ablation': 'none', 'stage': True})
        parent_exact[seed] = scores['earlier']
    for trial in trials:
        seed, architecture = trial['seed'], trial['architecture']; enabled = architecture == 'grounding'
        baseline = inputs['trials'][f'baseline_{architecture}-{seed}']
        temporal = inputs['trials'][f'temporal_augmented_{architecture}-{seed}']
        require(trial['parent'] == temporal['parent'] == baseline['parent'] == inputs['parents'][seed]['checkpoint']
            and trial['temporal_source_trial'] == temporal['name'] and trial['baseline_source_trial'] == baseline['name']
            and trial['prior_checkpoint'] == temporal['checkpoint'] == temporal['stages'][1]['checkpoint']
            and trial['document_reference_checkpoint'] == baseline['checkpoint'] == baseline['stages'][1]['checkpoint']
            and trial['parent_tuning_earlier_exact'] == parent_exact[seed]
            and trial['new_optimizer_steps'] == 0 and trial['training_executed'] is False
            and trial['fresh_targets_opened'] is trial['regression_targets_opened'] is False,
                'historical reference/candidate checkpoint bank binding differs')
        require({k: v for k, v in trial.items() if k != 'selection_record'} == read_ref(trial['selection_record']), 'selection record differs from frozen inventory')
        require([r['steps'] for r in trial['stages']] == [400, 800] and trial['document_reference']['steps'] == 800,
                'baseline800 and both historical temporal stages required')
        normalized, stage_audits = [], []
        all_stages = [('baseline', trial['document_reference'], baseline['stages'][1])]
        all_stages += [('temporal_augmented', stage, historical) for stage, historical in zip(trial['stages'], temporal['stages'])]
        for curriculum, stage, historical_stage in all_stages:
            require(stage['checkpoint'] == historical_stage['checkpoint'] and stage['new_optimizer_steps'] == 0
                and stage['historical_training_report'] == historical_stage['training_report'], 'stage reused checkpoint or historical training receipt differs')
            read_ref(stage['historical_training_report'], parse=False)
            cp = mixed.load_checkpoint(stage['checkpoint']['path'], expected_sha256=stage['checkpoint']['sha256'])
            require(cp['progress']['optimizer_steps'] == stage['steps'] and cp['config']['seed'] == seed
                and cp['config']['trigger_enabled'] is enabled
                and cp['source_parent_checkpoint_sha256'] == parent_digests[seed]
                and cp['training_count'] == (1752 if curriculum == 'baseline' else 2352)
                and cp['training_domain_counts'] == {'earlier': 1152, 'new': 600 if curriculum == 'baseline' else 1200},
                    'historical model steps/seed/architecture/curriculum differs')
            item = {'checkpoint': stage['checkpoint'], 'decoder_kind': 'mixed'}
            numbers = {'steps': stage['steps']}
            for panel in TUNING_COUNTS:
                reference = stage['tuning_' + panel]; payload = read_ref(reference)
                original = read_ref(historical_stage['tuning_' + panel]); sources = inputs['sources']['tuning_' + panel]
                measured = previous.score(payload['generation']['rows'], sources, inputs['tuning'][panel])
                require(payload == original and measured == payload['metrics']
                    and measured['exact'] == stage['tuning_' + panel + '_exact'] == historical_stage['tuning_' + panel + '_exact'],
                        'historical candidate single tuning changed')
                numbers[panel + '_exact'] = measured['exact']
                jobs.append({'kind': 'single', 'name': f"reference-{architecture}-{seed}/{curriculum}-{stage['steps']}/tuning_{panel}",
                    'model': item, 'generation': reference, 'sources': sources, 'ablation': 'none', 'stage': True})
            reference = stage['document_tuning']; payload = read_ref(reference)
            measured = score_documents(payload['generation'], inputs['document_sources']['document_tuning'], inputs['document_tuning'])
            require(payload['metrics'] == measured and stage['tuning_document_exact'] == measured['exact']
                and measured['count'] == 96 and measured['supported'] == 72 and measured['unsupported'] == 24,
                    'independent complete document tuning score differs')
            numbers['document_exact'] = measured['exact']
            jobs.append({'kind': 'document', 'name': f"reference-{architecture}-{seed}/{curriculum}-{stage['steps']}/document_tuning",
                'model': item, 'generation': reference, 'sources': inputs['document_sources']['document_tuning'],
                'boundary': frozen['boundaries']['document_tuning'], 'stage': True})
            stage_audits.append({'curriculum': curriculum, 'checkpoint': stage['checkpoint'], 'tuning': numbers,
                'historical_optimizer_steps': stage['steps'], 'new_optimizer_steps': 0})
            if curriculum == 'baseline':
                baseline_numbers = numbers
            else:
                earlier_ok = numbers['earlier_exact'] >= parent_exact[seed] - 1
                document_ok = numbers['document_exact'] >= baseline_numbers['document_exact'] - 1
                require(stage['earlier_retention_eligible'] is earlier_ok and stage['document_retention_eligible'] is document_ok
                    and stage['retention_eligible'] is (earlier_ok and document_ok), 'stage retention eligibility differs')
                normalized.append(numbers)
        chosen = retention_choice(normalized, parent_exact[seed], baseline_numbers['document_exact'], baseline_numbers['earlier_exact'])
        if chosen is None:
            expected_checkpoint, expected_steps, expected_curriculum, expected_selection = baseline['checkpoint'], 800, 'baseline', 'baseline_fallback'
        else:
            expected_checkpoint = next(row['checkpoint'] for row in trial['stages'] if row['steps'] == chosen['steps'])
            expected_steps, expected_curriculum, expected_selection = chosen['steps'], 'temporal_augmented', 'candidate'
        require(trial['checkpoint'] == expected_checkpoint and trial['selected_steps'] == expected_steps
            and trial['selected_curriculum'] == expected_curriculum and trial['selection'] == expected_selection,
                'independent document retention selection or baseline fallback differs')
        for policy in ('prior', 'document_retained'):
            item = models[f'{policy}_{architecture}-{seed}']; is_prior = policy == 'prior'
            expected = {'checkpoint': temporal['checkpoint'] if is_prior else expected_checkpoint,
                'selected_steps': 800 if is_prior else expected_steps,
                'curriculum': 'temporal_augmented' if is_prior else expected_curriculum,
                'selection': 'prior_selected' if is_prior else expected_selection,
                'decoder_kind': 'mixed', 'enabled': enabled, 'requested_enabled': enabled,
                'parent': trial['parent'], 'document_reference_checkpoint': baseline['checkpoint'],
                'selection_record': trial['selection_record'], 'new_optimizer_steps': 0,
                'source_trial_name': temporal['name'] if is_prior or expected_selection == 'candidate' else baseline['name'],
                'historical_trial_executed_steps': 800, 'selection_policy': policy, 'architecture': architecture, 'seed': seed,
                'arm': f'{policy}_{architecture}', 'name': f'{policy}_{architecture}-{seed}'}
            require(item == expected, 'selected/prior model slot attribution or fallback architecture differs')
        audits.append({'architecture': architecture, 'seed': seed, 'parent_earlier_exact': parent_exact[seed],
            'baseline_document_exact': baseline_numbers['document_exact'], 'baseline_earlier_exact': baseline_numbers['earlier_exact'],
            'stage_audits': stage_audits, 'selection': expected_selection, 'checkpoint': expected_checkpoint,
            'selected_steps': expected_steps, 'selected_curriculum': expected_curriculum, 'new_optimizer_steps': 0})
    return jobs, audits


def verify_boundaries(inputs, frozen):
    from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
    require(set(frozen['boundaries']) == set(DOCUMENT_COUNTS), 'all three learned boundary panels required')
    decoder = boundary.ClauseBoundaryDecoder(read_ref(inputs['boundary_checkpoint']))
    audits = []
    for panel, sources in inputs['document_sources'].items():
        expected = read_ref(frozen['boundaries'][panel])
        actual = clauses.decode_all(decoder, sources)
        require(actual == expected, 'independent frozen learned boundary replay differs: ' + panel)
        audits.append({'panel': panel, 'rows': len(sources), 'checkpoint': inputs['boundary_checkpoint'],
            'generation': frozen['boundaries'][panel], 'exact_recorded_payload_replay': True,
            'declared_learned_clause_occurrences': sum(r['plan']['clause_count'] for r in actual['rows'] if r['plan'] is not None),
            'target_access': False})
    return audits


def build_batches(entries, directory, args):
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    batches = []
    for start in range(0, len(entries), gate.MAX_ROWS):
        selected = entries[start:start + gate.MAX_ROWS]
        folder = directory / f'batch-{start // gate.MAX_ROWS:02d}'
        receipt = gate.build_qualified_legal(selected, toolchain=args.toolchain, lake_executable=args.lake_executable,
            timeout_seconds=60, output_directory=folder).to_dict()
        reference = ref(folder / 'qualified-receipt.json')
        require(calendar_summary.verify_receipt(reference, selected) == receipt, 'independent native compiler receipt differs')
        batches.append({'candidate_ids': [r['candidate']['candidate_id'] for r in selected], 'receipt': reference,
            'build_passed': receipt['build_passed'], 'backend_executed': receipt['backend_executed'], 'command': receipt['command']})
    return batches


def document_build_accounting(selection, batches, metric):
    ids = {row['id'] for row in metric['rows']}
    selected = [row['candidate']['candidate_id'] for row in selection['rows']]
    excluded = [row['candidate_id'] for row in selection['excluded']]
    require(len(ids) == len(selected) + len(excluded) == 96 and set(selected) | set(excluded) == ids,
            'complete document build denominator required')
    require([identity for batch in batches for identity in batch['candidate_ids']] == selected, 'document build batch coverage differs')
    built = {identity for batch in batches if batch['build_passed'] for identity in batch['candidate_ids']}
    exact = {row['id'] for row in metric['rows'] if row['exact']}
    canonical = {row['id'] for row in metric['rows'] if row['canonical_rule_list_exact']}
    return {'count': 96, 'composed': metric['composed'], 'abstained': metric['abstained'],
        'supported': len(selected), 'excluded': len(excluded), 'built': len(built),
        'built_exact': len(built & exact), 'built_reference_mismatch': len(built - exact),
        'built_canonical_only_exact': len(built & canonical),
        'build_invocations': len(batches), 'actual_lake_build_executed': any(r['backend_executed'] for r in batches)}


def independent_layout(row):
    import re
    from scripts.ops.legal_ir import prepare_legal_grounding_curriculum as grounding
    text = row['source_text']; pieces = []; cursor = 0
    for start, end, field in sorted((span[0], span[1], field) for field, span in row['facet_spans'].items() if span is not None):
        require(type(start) is int and type(end) is int and cursor <= start < end <= len(text), 'layout coordinates overlap or escape source')
        pieces += [text[cursor:start], '<' + field + '>']; cursor = end
    pieces.append(text[cursor:])
    masked = ''.join(pieces).casefold()
    masked = re.sub(r'\b\d+\b', '#', masked)
    masked = re.sub(r'(?<=\()\w(?=\))', '#', masked)
    masked = ' '.join(masked.split())
    for phrase in sorted(grounding.TRIGGER_MEANINGS, key=len, reverse=True):
        masked = re.sub(r'\b' + re.escape(phrase) + r'\b', '<modal>', masked)
    return masked.rstrip('.;')


def document_audit_clauses(documents):
    import re
    fields = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
    result = []
    for document in documents:
        for ordinal, clause in enumerate(document['clauses']):
            text = document['source_text'][clause['char_start']:clause['char_end']]
            coordinates = {}
            for field in fields:
                value = clause['rule'][field]
                if field in fields[3:]:
                    require(len(value) <= 1, 'layout audit supports singleton qualifier profile')
                    value = value[0] if value else None
                if value is None:
                    coordinates[field] = None
                else:
                    occurrences = list(re.finditer(re.escape(value), text))
                    require(len(occurrences) == 1, 'historical layout atom occurrence is ambiguous')
                    coordinates[field] = [occurrences[0].start(), occurrences[0].end()]
            result.append({'id': f"{document['candidate_id']}-clause-{ordinal}", 'source_text': text, 'facet_spans': coordinates})
    return result


def audit_construction_exposure(historical_inputs, manifest, single_targets, document_targets, posthoc):
    """Post-build local layout audit; never a universal construction/semantic claim."""
    pools = {'earlier_training': [r for r in historical_inputs['training']['baseline'] if r['domain'] == 'earlier'],
        'new_training': [r for r in historical_inputs['training']['baseline'] if r['domain'] == 'new'],
        'temporal_training': historical_inputs['training']['temporal_augmented'][1752:],
        **{name + '_tuning': rows for name, rows in historical_inputs['tuning'].items()}}
    admitted = set(pools)
    pools.update(exposed_grounding150=single_targets['exposed_regression'], exposed_mixed144=single_targets['mixed_regression'],
                 exposed_temporal180=single_targets['temporal_regression'])
    earlier = []
    for row in single_targets['earlier_regression']:
        fields = {}
        for field in ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal'):
            value = row['source_spans'][field]
            fields[field] = (value[0] if value else None) if field in ('conditions', 'exceptions', 'temporal') else (value or None)
        earlier.append({**row, 'facet_spans': fields})
    pools['exposed_earlier192'] = earlier
    for split, reference in manifest['inputs']['prior_document_references'].items():
        pools['boundary_' + split + '_clauses'] = document_audit_clauses(read_ref(reference))
        if split == 'train': admitted.add('boundary_train_clauses')
    layouts = {name: {independent_layout(row) for row in rows} for name, rows in pools.items()}
    exposure, novelty, annotations = posthoc['exposure_audit'], posthoc['novelty_evidence'], posthoc['annotation_ledger']
    require(exposure['known_pool_counts'] == {name: len(rows) for name, rows in pools.items()}
        and exposure['known_role_masked_layouts'] == {name: sorted(rows) for name, rows in layouts.items()},
            'independent historical exposure inventory/layouts differ')
    require(novelty['rows'] == exposure['single_rows'] and novelty['anchor_rows'] == exposure['anchor_rows']
        and novelty['coordinate_derived_reference_evidence'] is True, 'novelty evidence is not the committed posthoc exposure evidence')
    fresh_by_id = {r['id']: r for r in single_targets['fresh']}; anchor_by_id = {r['id']: r for r in single_targets['seen_layout_anchor']}
    annotations_by_id = {r['id']: r for r in annotations['single_rows']}
    anchors_by_id = {r['id']: r for r in annotations['anchor_rows']}
    require(len(novelty['rows']) == len(fresh_by_id) == len(annotations_by_id) == 180
        and len(novelty['anchor_rows']) == len(anchor_by_id) == len(anchors_by_id) == 30, 'fresh/anchor exposure row inventory differs')
    family_shapes, groups = {}, {}
    for row in novelty['rows']:
        target = fresh_by_id[row['id']]; annotation = annotations_by_id[row['id']]
        shape = independent_layout(target)
        matches = sorted(name for name, values in layouts.items() if shape in values)
        require(row['source_sha256'] == previous.source_rows([target])[0]['source_sha256']
            and row['role_masked_layout'] == shape and row['matching_pools'] == matches == []
            and row['family'] == annotation['family'], 'fresh single local construction holdout differs')
        family_shapes.setdefault(row['family'], set()).add(shape)
        groups.setdefault(annotation['case_group'], []).append(target)
    require(set(family_shapes) == set(manifest['heldout_families']) and len(family_shapes) == 6
        and len(set.union(*family_shapes.values())) == 6, 'six distinct locally held-out rendering layouts required')
    anchor_groups = {}
    for row in novelty['anchor_rows']:
        target = anchor_by_id[row['id']]; annotation = anchors_by_id[row['id']]; shape = independent_layout(target)
        matches = sorted(name for name in admitted if shape in layouts[name])
        require(row['role_masked_layout'] == shape and row['matching_admitted_pools'] == matches
            and row['source_sha256'] == previous.source_rows([target])[0]['source_sha256']
            and row['case_group'] == annotation['case_group']
            and any('training' in name or name == 'boundary_train_clauses' for name in matches), 'anchor lacks verified training-layout exposure')
        anchor_groups[annotation['case_group']] = target
    require(len(groups) == len(anchor_groups) == 30 and set(groups) == set(anchor_groups)
        and all(len(rows) == 6 and all(row['canonical_ir'] == anchor_groups[group]['canonical_ir'] for row in rows) for group, rows in groups.items()),
            'matched anchor/new-family case semantics or complete six-family case groups differ')
    tuned = document_audit_clauses(document_targets['document_tuning'])
    expected_tuning = []
    for row in tuned:
        shape = independent_layout(row); matches = sorted(name for name in admitted if shape in layouts[name])
        require(any('training' in name or name == 'boundary_train_clauses' for name in matches), 'document tuning clause lacks actual training-layout exposure')
        expected_tuning.append({'id': row['id'], 'role_masked_layout': shape, 'matching_admitted_pools': matches})
    require(exposure['document_tuning_clause_exposure'] == expected_tuning, 'document tuning layout evidence differs')
    fresh_clauses = document_audit_clauses(document_targets['fresh_documents'])
    require(all(not any(independent_layout(row) in values for values in layouts.values()) for row in fresh_clauses),
            'fresh supported document clause repeats a compared historical layout')
    return {'known_pool_counts': {name: len(rows) for name, rows in pools.items()},
        'fresh_single_rows_verified': 180, 'matched_seen_layout_anchor_rows_verified': 30, 'matched_case_groups': 30,
        'fresh_family_count': 6, 'fresh_supported_document_clause_occurrences': len(fresh_clauses),
        'document_tuning_clause_occurrences': len(tuned), 'local_masked_layout_holdout_verified': True,
        'matched_anchor_canonical_semantics_verified': True, 'fresh_layout_matches_in_compared_pools': 0,
        'universal_language_model_or_semantic_construction_novelty_claimed': False,
        'scope': 'Exact role-masked layouts versus explicitly pinned local pools; no universal pretraining novelty, legal adjudication, or unsupported-wrapper novelty claim'}


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_construction_retention_experiment as runner
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(1 <= args.workers <= 3, 'one to three independent inference workers required')
    directory, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    frozen_ref = ref(directory / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == runner.SCHEMA and frozen['all_selection_and_generation_complete'] is True
        and frozen['challenge_targets_opened'] is frozen['regression_targets_opened'] is frozen['training_executed'] is False
        and frozen['executed_optimizer_updates'] == 0, 'complete selection-only source generation freeze required')
    plan = read_ref(frozen['plan'])
    expected_arms = {arm: {'selection_policy': 'prior' if arm.startswith('prior_') else 'document_retained',
        'architecture': 'grounding' if arm.endswith('_grounding') else 'continuation', 'enabled': arm.endswith('_grounding')} for arm in ARMS}
    require(plan['arms'] == expected_arms and plan['seeds'] == list(SEEDS) and plan['candidate_steps'] == [400, 800]
        and plan['counts'] == SINGLE_COUNTS and plan['document_counts'] == DOCUMENT_COUNTS
        and plan['executed_optimizer_updates'] == 0 and plan['training_executed'] is False
        and plan['earlier_retention_tolerance'] == plan['document_retention_tolerance'] == 1
        and plan['document_reference'] == 'same_architecture_seed_baseline_curriculum_selected800'
        and plan['fresh_targets_opened'] is plan['regression_targets_opened'] is False,
            'predeclared matched document-retention protocol differs')
    require(all(sha(path) == wanted for path, wanted in plan['producer_pins'].items()), 'frozen selection/generation producer drift')
    read_ref(plan['config'], parse=False); inputs = runner.load_config(plan['config']['path'])
    require(read_ref(frozen['sources']) == inputs['sources'] and read_ref(frozen['document_sources']) == inputs['document_sources']
        and read_ref(frozen['heads']) == frozen['models'] and plan['boundary_checkpoint'] == inputs['boundary_checkpoint'],
            'frozen source/model/boundary inventory differs')
    inventory = verify_panel_inventory(frozen['models'], frozen['files'], frozen['document_files'])
    require(frozen['baseline_fallbacks'] == [r['name'] for r in frozen['models'] if r['selection'] == 'baseline_fallback'], 'fallback model inventory differs')
    # Common admitted tuning labels must equal the original historical labels.
    historical_plan = read_ref(inputs['historical']['plan'])
    historical_inputs = runner.historical.load_config(historical_plan['config']['path'])
    require(inputs['tuning'] == historical_inputs['tuning'], 'historical single tuning annotations changed')
    output.mkdir(parents=True, exist_ok=False)
    pins = dict(plan['producer_pins'])
    for module in (sys.modules[__name__], runner, prior, previous, clauses, transfer, calendar, calendar_summary, compose, gate):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    boundary_audits = verify_boundaries(inputs, frozen)
    selection = read_ref(frozen['selections'])
    jobs, selection_audits = verify_selection(inputs, frozen, selection)
    selection_ref = write(output / 'selection-audit.json', {'schema': SCHEMA, 'selection_freeze': frozen['selections'],
        'trials': selection_audits, 'historical_checkpoint_bank_preserved': True, 'common_single_tuning_unchanged': True,
        'document_floor_uses_same_architecture_baseline800': True, 'new_optimizer_updates': 0, **FALSE})
    singles, documents = {}, {}
    for item in frozen['models']:
        name = item['name']; singles[name] = {}; documents[name] = {}
        for panel, reference in frozen['files'][name].items():
            sources = inputs['sources']['fresh' if panel == 'fresh_disabled' else panel]
            singles[name][panel] = read_ref(reference)
            require(len(singles[name][panel]['rows']) == len(sources), 'selected single panel dropped rows')
            jobs.append({'kind': 'single', 'name': name + '/' + panel, 'model': item, 'sources': sources,
                'generation': reference, 'ablation': 'disabled' if panel == 'fresh_disabled' else 'none'})
        for panel, reference in frozen['document_files'][name].items():
            sources = inputs['document_sources'][panel]; documents[name][panel] = read_ref(reference)
            require(len(documents[name][panel]['rows']) == len(sources), 'selected document panel dropped rows')
            jobs.append({'kind': 'document', 'name': name + '/' + panel, 'model': item, 'sources': sources,
                'generation': reference, 'boundary': frozen['boundaries'][panel]})
    require(sum(len(j['sources']) for j in jobs if j.get('stage') and j['kind'] == 'single') == 6552
        and sum(len(j['sources']) for j in jobs if j.get('stage') and j['kind'] == 'document') == 1728
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'single') == 18900
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'document') == 4320,
            'complete baseline/candidate/parent tuning and selected inference denominators differ')
    replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(replay_job, job) for job in jobs]):
            value = future.result(); replays.append(value)
            print({'phase': 'replayed', 'panel': value['name'], 'kind': value['kind'], 'rows': value['rows']}, flush=True)
    # Reused aliases must reproduce every panel, not merely aggregate scores.
    models = frozen['models']
    for i, left in enumerate(models):
        for right in models[i + 1:]:
            if left['checkpoint'] == right['checkpoint']:
                require(singles[left['name']] == singles[right['name']] and documents[left['name']] == documents[right['name']],
                        'same reused checkpoint differs across model slots')
    replay_ref = write(output / 'replay-frozen.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'panels': sorted(replays, key=lambda row: row['name']), 'boundary_panels': boundary_audits,
        'single_rows': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_rows': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'clause_occurrences_replayed': sum(r.get('clause_occurrences_replayed', 0) for r in replays),
        'selection_audit': selection_ref, 'fresh_and_regression_targets_opened': False, 'new_optimizer_updates': 0,
        'unselected_candidate_fresh_outputs_generated': False, **FALSE})
    selections = {}
    for item in models:
        name = item['name']
        selected = calendar.select_candidates(inputs['sources']['fresh'], singles[name]['fresh']['rows'], toolchain=args.toolchain, policy=calendar.POLICY)
        lookup = {source['id']: (source, prediction) for source, prediction in zip(inputs['sources']['fresh'], singles[name]['fresh']['rows'])}
        for entry in selected['rows']:
            source, prediction = lookup[entry['candidate']['candidate_id']]; calendar_summary.verify_entry(source, prediction, entry)
        require(selected['source_count'] == len(selected['rows']) + len(selected['excluded']) == 180, 'fresh single build selection dropped rows')
        anchor = calendar.select_candidates(inputs['sources']['seen_layout_anchor'], singles[name]['seen_layout_anchor']['rows'], toolchain=args.toolchain, policy=calendar.POLICY)
        anchor_lookup = {source['id']: (source, prediction) for source, prediction in zip(inputs['sources']['seen_layout_anchor'], singles[name]['seen_layout_anchor']['rows'])}
        for entry in anchor['rows']:
            source, prediction = anchor_lookup[entry['candidate']['candidate_id']]; calendar_summary.verify_entry(source, prediction, entry)
        require(anchor['source_count'] == len(anchor['rows']) + len(anchor['excluded']) == 30, 'matched anchor build selection dropped rows')
        selections[name] = {'single': selected, 'anchor': anchor, 'document': document_selection(documents[name]['fresh_documents']['rows'],
            inputs['document_sources']['fresh_documents'], toolchain=args.toolchain)}
    selection_build_ref = write(output / 'build-selection-frozen.json', {'models': selections, 'replay': replay_ref,
        'single_source_slots': 2700, 'anchor_source_slots': 450, 'document_source_slots': 1440, 'fresh_targets_opened': False,
        'interpretation_policy': calendar.POLICY, 'canonical_references_used_for_selection': False})
    builds = {}
    for item in models:
        name = item['name']; builds[name] = {}
        for kind in ('single', 'anchor', 'document'):
            builds[name][kind] = build_batches(selections[name][kind]['rows'], output / 'builds' / name / kind, args)
        print({'phase': 'built', 'model': name, 'single_supported': len(selections[name]['single']['rows']),
               'document_supported': len(selections[name]['document']['rows'])}, flush=True)
    build_ref = write(output / 'builds-frozen.json', {'schema': SCHEMA, 'models': builds, 'selections': selection_build_ref,
        'replay': replay_ref, 'fresh_and_regression_targets_opened': False, **FALSE})
    # Fresh single/document labels and all exposed regression labels open only here.
    config, manifest = inputs['config'], inputs['manifest']
    single_target_refs = {'fresh': manifest['artifacts']['challenge_targets'], 'seen_layout_anchor': manifest['artifacts']['anchor_targets'], **{name + '_regression': config[name + '_regression_targets']
        for name in ('earlier', 'exposed', 'mixed', 'temporal')}}
    single_targets = {'tuning_' + panel: inputs['tuning'][panel] for panel in TUNING_COUNTS}
    for panel, reference in single_target_refs.items():
        single_targets[panel] = previous.reference_rows(read_ref(reference), inputs['sources'][panel])
        for row in single_targets[panel]:
            if 'canonical_target_sha256' in row: require(row['canonical_target_sha256'] == digest(row['canonical_ir']), 'reference canonical commitment differs')
    single_targets['fresh_disabled'] = single_targets['fresh']
    document_target_refs = {'fresh_documents': manifest['artifacts']['document_challenge_targets'], 'exposed_documents': config['exposed_document_targets']}
    document_targets = {'document_tuning': inputs['document_tuning']}
    for panel, reference in document_target_refs.items():
        document_targets[panel] = read_ref(reference)
        require(clauses.source_rows(document_targets[panel]) == inputs['document_sources'][panel], 'document posthoc reference/source commitment differs')
    # Reference-derived role masks remain sealed until builds, even when called novelty evidence.
    posthoc_refs = {key: manifest['artifacts'][key] for key in ('novelty_evidence', 'exposure_audit', 'annotation_ledger')}
    posthoc = {key: read_ref(reference) for key, reference in posthoc_refs.items()}
    exposure_audit = audit_construction_exposure(historical_inputs, manifest, single_targets, document_targets, posthoc)
    exposure_ref = write(output / 'construction-exposure-audit.json', exposure_audit)
    scored_singles, scored_documents, report_models = {}, {}, []
    for item in models:
        name = item['name']; scored_singles[name] = {}; scored_documents[name] = {}
        for panel, generation in singles[name].items():
            sources = inputs['sources']['fresh' if panel == 'fresh_disabled' else panel]
            scored_singles[name][panel] = prior.annotated_metrics(generation, sources, single_targets[panel],
                supervised_trigger=item['decoder_kind'] == 'mixed' and item['enabled'])
        for panel, generation in documents[name].items():
            scored_documents[name][panel] = score_documents(generation, inputs['document_sources'][panel], document_targets[panel])
        exact = {row['id']: row['exact'] for row in scored_singles[name]['fresh']['rows']}
        anchor_exact = {row['id']: row['exact'] for row in scored_singles[name]['seen_layout_anchor']['rows']}
        report_models.append({**item, 'single_metrics': {p: {k: v for k, v in m.items() if k != 'rows'} for p, m in scored_singles[name].items()},
            'document_metrics': {p: {k: v for k, v in m.items() if k != 'rows'} for p, m in scored_documents[name].items()},
            'single_builds': prior.build_accounting(selections[name]['single'], builds[name]['single'], exact),
            'anchor_builds': prior.build_accounting(selections[name]['anchor'], builds[name]['anchor'], anchor_exact),
            'document_builds': document_build_accounting(selections[name]['document'], builds[name]['document'], scored_documents[name]['fresh_documents'])})
    totals = {}
    for arm in (*ARMS, 'parent'):
        group = [m for m in report_models if m['arm'] == arm]
        totals[arm] = {'single': {panel: {key: sum(m['single_metrics'][panel][key] for m in group)
            for key in ('count', 'decoded', 'abstained', 'exact')} for panel in SINGLE_COUNTS},
            'document': {panel: {key: sum(m['document_metrics'][panel][key] for m in group)
            for key in ('count', 'supported', 'unsupported', 'composed', 'abstained', 'exact', 'canonical_rule_list_exact',
                        'occurrence_boundaries_exact', 'decision_exact', 'unsupported_accepted')} for panel in DOCUMENT_COUNTS},
            'single_builds': {key: sum(m['single_builds'][key] for m in group) for key in ('count', 'built', 'built_exact', 'built_reference_mismatch', 'build_invocations')},
            'anchor_builds': {key: sum(m['anchor_builds'][key] for m in group) for key in ('count', 'built', 'built_exact', 'built_reference_mismatch', 'build_invocations')},
            'document_builds': {key: sum(m['document_builds'][key] for m in group) for key in ('count', 'built', 'built_exact', 'built_reference_mismatch', 'built_canonical_only_exact', 'build_invocations')},
            'baseline_fallbacks': sum(m['selection'] == 'baseline_fallback' for m in group)}
    details_ref = write(output / 'scored-details.json', {'single': scored_singles, 'document': scored_documents})
    paired = []
    for seed in SEEDS:
        for architecture in ('continuation', 'grounding'):
            left, right = f'document_retained_{architecture}-{seed}', f'prior_{architecture}-{seed}'
            for kind, metrics in (('single', scored_singles), ('document', scored_documents)):
                for panel in metrics[left]:
                    a = {r['id']: r['exact'] for r in metrics[left][panel]['rows']}; b = {r['id']: r['exact'] for r in metrics[right][panel]['rows']}
                    require(set(a) == set(b), 'paired model source coverage differs')
                    paired.append({'kind': kind, 'panel': panel, 'left': left, 'right': right, 'count': len(a),
                        'left_only_exact': sum(a[i] and not b[i] for i in a), 'right_only_exact': sum(b[i] and not a[i] for i in a),
                        'both_exact': sum(a[i] and b[i] for i in a)})
    require(all(sha(path) == wanted for path, wanted in pins.items()), 'qualifier or producer source drift')
    require(runner.load_config(plan['config']['path']) == inputs, 'selection/source input closure changed')
    for reference in [frozen_ref, frozen['plan'], frozen['sources'], frozen['document_sources'], frozen['selections'], frozen['heads'],
        *single_target_refs.values(), *document_target_refs.values(), *posthoc_refs.values(),
        *[r for panels in frozen['files'].values() for r in panels.values()], *[r for panels in frozen['document_files'].values() for r in panels.values()]]:
        read_ref(reference, parse=False)
    result = {'schema': SCHEMA, 'generation_freeze': frozen_ref, 'selection_audit': selection_ref, 'replay': replay_ref,
        'builds': build_ref, 'details': details_ref, 'models': report_models, 'totals': totals, 'paired_comparisons': paired,
        'construction_exposure_audit': exposure_ref, 'posthoc_evidence': posthoc_refs, 'posthoc_evidence_schemas': {k: v.get('schema') if isinstance(v, dict) else None for k, v in posthoc.items()},
        'producer_pins': pins, 'baseline_fallbacks': frozen['baseline_fallbacks'], 'executed_optimizer_updates': 0,
        'single_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'boundary_source_documents_replayed': sum(r['rows'] for r in boundary_audits),
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes': True,
        'reference_derived_novelty_evidence_opened_after_build_freeze': True,
        'test_results_used_for_selection_or_gate_revision': False, 'new_checkpoint_training_performed': False,
        'document_exact_metric': 'ordered canonical rules AND exact source occurrence intervals; canonical-only counts also retained',
        'construction_novelty_independently_established': False,
        'construction_scope': 'Authored rendering-family holdout claims require separate review of posthoc source/role-masked exposure evidence; new strings alone do not establish construction novelty',
        'scope': 'Selection-only document retention over a frozen checkpoint bank; restricted source-copy/calendar profile, with all abstentions and compiler/reference mismatches retained',
        'actual_lake_build_invocations': sum(batch['backend_executed'] for kinds in builds.values() for batches in kinds.values() for batch in batches),
        'build_attempts': sum(len(batches) for kinds in builds.values() for batches in kinds.values()), **FALSE}
    write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'totals': totals, 'fallbacks': frozen['baseline_fallbacks']}, flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--lake-executable', required=True); parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    parser.add_argument('--workers', type=int, default=3)
    run(parser.parse_args())
