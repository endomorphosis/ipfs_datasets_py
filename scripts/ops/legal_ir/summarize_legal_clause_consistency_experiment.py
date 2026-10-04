#!/usr/bin/env python3
"""Independent audit of paired-clause consistency training and native builds.

Frozen parent decoders and boundary checkpoints remain controls. Source-only
inference and native builds freeze before fresh references or layout evidence.
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
from scripts.ops.legal_ir import summarize_legal_boundary_curriculum_experiment as boundary_qualification
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from scripts.ops.legal_ir import run_legal_grounding_experiment as previous
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary

require, digest, read_ref, ref, write, sha = retained.require, retained.digest, retained.read_ref, retained.ref, retained.write, retained.sha
SCHEMA = 'legal-clause-consistency-independent-qualification/v1'
SEEDS = (1729, 1730, 1731)
OBJECTIVES = ('ce', 'consistency')
POLICIES = ('parent', *OBJECTIVES)
ARCHITECTURES = ('continuation', 'grounding')
SINGLE_COUNTS = {'tuning_earlier': 96, 'tuning_temporal': 120, 'tuning_new': 96, 'fresh': 144,
    'prior_construction': 180, 'earlier_regression': 192, 'temporal_regression': 180}
DOCUMENT_COUNTS = {'document_tuning': 96, 'fresh_documents': 96, 'prior_boundary_documents': 96, 'exposed_documents': 96}
FALSE = retained.FALSE


def selection_choice(stages, parent):
    bounds = {'earlier': 96, 'temporal': 120, 'document_parent': 72, 'document_expanded': 72}
    require(set(parent) == set(bounds) and all(type(parent[k]) is int and 0 <= parent[k] <= n for k, n in bounds.items()),
            'closed bounded same-parent retention metrics required')
    require(type(stages) is list and [r.get('steps') for r in stages] == [400, 800], 'both additional-update stages required')
    fields = {**bounds, 'new': 96, 'guard_parent': 24, 'guard_expanded': 24}
    for stage in stages:
        require(set(stage) == {'steps', *fields} and all(type(stage[k]) is int and 0 <= stage[k] <= n for k, n in fields.items()),
                'closed bounded tuning-only metrics required')
    eligible = [r for r in stages if all(r[k] >= parent[k] - 1 for k in bounds)
        and r['guard_parent'] == r['guard_expanded'] == 0]
    return max(eligible, key=lambda r: (r['new'], r['temporal'], r['document_expanded'], r['document_parent'], r['earlier'], -r['steps'])) if eligible else None


def verify_pairs(rows, pairs):
    """Equivalent full targets and unique source occurrences, not guessed labels."""
    required = {'pair_id', 'case_group', 'left_id', 'right_id', 'canonical_ir_sha256'}
    lookup = {r['id']: r for r in rows}
    require(len(rows) == 2 * len(pairs) and len(lookup) == len(rows)
        and len({r['source_text'] for r in rows}) == len(rows), 'unique two-row semantic pair inventory required')
    members, case_groups, pair_ids, case_rules = set(), set(), set(), {}
    for pair in pairs:
        require(set(pair) == required and all(type(pair[k]) is str and pair[k] for k in required), 'closed semantic pair metadata required')
        require(pair['pair_id'] not in pair_ids and pair['left_id'] != pair['right_id'] and {pair['left_id'], pair['right_id']} <= set(lookup)
            and not {pair['left_id'], pair['right_id']} & members, 'pair identity or source membership overlaps')
        left, right = lookup[pair['left_id']], lookup[pair['right_id']]
        require(left['canonical_ir'] == right['canonical_ir'] and digest(left['canonical_ir']) == pair['canonical_ir_sha256'],
                'paired examples must have identical complete canonical semantics')
        for row in (left, right):
            require(row['domain'] == 'new' and row['trigger_supervised'] is True and row['trigger_span'] is not None,
                    'new paired rows require explicit trigger supervision')
        members.update((pair['left_id'], pair['right_id'])); case_groups.add(pair['case_group']); pair_ids.add(pair['pair_id'])
        case_rules.setdefault(pair['case_group'], []).append(left['canonical_ir']['rules'][0])
    require(members == set(lookup), 'semantic pair inventory dropped rows')
    require(all(len(rules) == 2 for rules in case_rules.values()), 'two contrastive meaning pairs per lexical case required')
    for first, second in case_rules.values():
        changed = [field for field in first if first[field] != second[field]]
        require(len(changed) == 1 and changed[0] in ('conditions', 'exceptions', 'temporal')
            and bool(first[changed[0]]) != bool(second[changed[0]]),
            'contrastive meaning groups must differ only by one optional presence bit')
    return {'pairs': len(pairs), 'rows': len(rows), 'case_groups': sorted(case_groups), 'pair_ids': sorted(pair_ids),
        'complete_canonical_semantics_equal': True, 'ordered_pair_manifest_sha256': digest(pairs)}


def single_error_metrics(generation, sources, references, *, enabled):
    result = retained.prior.annotated_metrics(generation, sources, references, supervised_trigger=enabled)
    targets = {r['id']: r for r in references}
    counts = Counter(); modality = Counter(); rows = []
    for source, prediction in zip(sources, generation['rows']):
        gold = targets[source['id']]['canonical_ir']['rules'][0]
        accepted = prediction['status'] == 'decoded'
        actual = prediction['canonical_ir']['rules'][0] if accepted else None
        modality[gold['modality'] + '->' + (actual['modality'] if accepted else 'abstained')] += 1
        overlap = prediction.get('reason') == 'copied_spans_overlap'
        counts['overlap_abstentions'] += overlap
        record = {'id': source['id'], 'decoded': accepted, 'overlap_abstention': overlap,
            'reason': prediction.get('reason'), 'reference_modality': gold['modality'],
            'predicted_modality': actual['modality'] if accepted else 'abstained'}
        for facet in ('conditions', 'exceptions', 'temporal'):
            wanted = bool(gold[facet]); got = bool(actual[facet]) if accepted else None
            counts[facet + '_reference_present'] += wanted
            counts[facet + '_reference_absent'] += not wanted
            counts[facet + '_present_reference_abstained'] += wanted and not accepted
            counts[facet + '_absent_reference_abstained'] += not wanted and not accepted
            counts[facet + '_decoded_omissions'] += bool(accepted and wanted and not got)
            counts[facet + '_decoded_spurious_insertions'] += bool(accepted and not wanted and got)
            counts[facet + '_decoded_wrong_atom'] += bool(accepted and wanted and got and actual[facet] != gold[facet])
            record[facet] = {'reference_present': wanted, 'predicted_present': got,
                'decoded_omission': bool(accepted and wanted and not got),
                'decoded_spurious_insertion': bool(accepted and not wanted and got)}
        rows.append(record)
    require(sum(modality.values()) == result['count'] and len(rows) == result['count'], 'single error metrics dropped abstentions')
    return {**result, 'error_counts': dict(counts), 'modality_confusion_including_abstentions': dict(modality), 'error_rows': rows}


def replay_job(job):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_clause_consistency_experiment as runner
    if job['kind'] == 'boundary':
        return boundary_qualification.replay_job(job)
    item = job['model']; expected = read_ref(job['generation'])
    if job.get('stage'): expected = expected['generation']
    decoder = runner.load_decoder(item['checkpoint'], item['decoder_kind'])
    copied = occurrences = 0
    if job['kind'] == 'single':
        actual = previous.generate(decoder, job['sources'], ablation='none')
        for source, prediction in zip(job['sources'], actual['rows']):
            copied += retained.prior.source_audit.assert_source_copy(prediction, source)
    else:
        frozen_boundaries = read_ref(job['boundary'])
        actual = {'rows': clauses.integrate(frozen_boundaries, job['sources'], decoder),
            'target_access': False, 'references_supplied': False, 'training_executed': False}
        by_id = {r['candidate_id']: r for r in frozen_boundaries['rows']}
        for row in actual['rows']:
            segment = by_id[row['candidate_id']]
            require(row['segmentation_status'] == segment['status'], 'pipeline changed frozen segmentation status')
            if segment['plan'] is None:
                require(row['composition'] is row['clause_generation'] is None, 'boundary abstention emitted clause predictions')
            else:
                plan = segment['plan']
                retained.compose.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
                require(len(row['clause_generation']['rows']) == plan['clause_count'], 'pipeline clause occurrence inventory differs')
                for clause, prediction in zip(plan['clauses'], row['clause_generation']['rows']):
                    copied += retained.prior.source_audit.assert_source_copy(prediction, clause); occurrences += 1
                if row['composition'] is not None:
                    require(row['composition']['source_plan'] == plan, 'pipeline changed frozen source occurrence intervals')
                    retained.compose.validate_composition(row['composition'], expected_plan_sha256=plan['plan_sha256'])
    require(actual == expected, 'independent full numerical replay differs: ' + job['name'])
    return {'kind': job['kind'], 'name': job['name'], 'rows': len(job['sources']), 'generation': job['generation'],
        'checkpoint': item['checkpoint'], 'boundary': job.get('boundary'), 'source_inputs_sha256': digest(job['sources']),
        'recorded_generation_sha256': digest(actual), 'exact_recorded_payload_replay': True,
        'clause_occurrences_replayed': occurrences, 'copied_facets_verified': copied,
        'stage_tuning': job.get('stage', False), 'target_access': False}


def verify_inventory(models, pipelines, files, document_files, heads, boundaries):
    expected_models = {f'{objective}_{architecture}-{seed}' for objective in POLICIES
        for architecture in ARCHITECTURES for seed in SEEDS}
    expected_pipelines = {name + '__' + policy for name in expected_models for policy in ('parent', 'expanded')}
    expected_heads = {'parent', *(f'expanded-{seed}' for seed in SEEDS)}
    require(len(models) == 18 and {m['name'] for m in models} == set(files) == expected_models
        and len(pipelines) == 36 and {p['name'] for p in pipelines} == set(document_files) == expected_pipelines
        and set(heads) == set(boundaries) == expected_heads,
        'complete18 single models/36 document pipelines/four fixed boundary heads required')
    by_model = {m['name']: m for m in models}
    for model in models:
        require(model['name'] == f"{model['objective']}_{model['architecture']}-{model['seed']}"
            and model['enabled'] is (model['architecture'] == 'grounding')
            and model['decoder_kind'] in ('mixed', 'consistency')
            and set(files[model['name']]) == set(SINGLE_COUNTS), 'single model architecture, seed or panel inventory differs')
        if model['objective'] == 'parent':
            require(model['decoder_kind'] == 'mixed' and model['selection'] == 'unchanged_parent'
                and model['selected_steps'] == model['executed_steps'] == 0,
                'original same-architecture temporal800 control attribution differs')
    for pipeline in pipelines:
        model = by_model[pipeline['source_model_name']]; policy = pipeline['boundary_policy']
        require(policy in ('parent', 'expanded') and pipeline['name'] == model['name'] + '__' + policy
            and pipeline['boundary_head'] == ('parent' if policy == 'parent' else f"expanded-{model['seed']}")
            and set(document_files[pipeline['name']]) == set(DOCUMENT_COUNTS)
            and all(pipeline[k] == model[k] for k in ('architecture', 'objective', 'seed', 'checkpoint', 'decoder_kind', 'enabled', 'selection', 'selected_steps')),
            'paired pipeline checkpoint or fixed same-seed boundary binding differs')
    require(all(set(panels) == set(DOCUMENT_COUNTS) for panels in boundaries.values()), 'fixed boundary panel inventory differs')
    return {'single_model_slots': 18, 'document_pipeline_slots': 36, 'fixed_boundary_heads': 4,
        'selected_single_rows': 18144, 'selected_pipeline_documents': 13824, 'fixed_boundary_documents': 1536}


def verify_fitting(inputs):
    manifest = inputs['manifest']
    baseline = read_ref(manifest['replay_inputs']['baseline'])
    temporal = read_ref(manifest['replay_inputs']['temporal'])
    wanted = {'earlier': [r for r in baseline if r['domain'] == 'earlier'],
        'prior_new': [r for r in baseline if r['domain'] == 'new'], 'temporal': temporal}
    require(inputs['replay'] == wanted and {k: len(v) for k, v in wanted.items()} == {'earlier': 1152, 'prior_new': 600, 'temporal': 600},
            'historical replay order or labels changed')
    train = read_ref(manifest['artifacts']['new_training']); tune = read_ref(manifest['artifacts']['new_tuning'])
    pairs = read_ref(manifest['artifacts']['training_pairs']); tuning_pairs = read_ref(manifest['artifacts']['tuning_pairs'])
    require(inputs['training'] == baseline + temporal + train and inputs['new_train'] == train and inputs['training_pairs'] == pairs
        and inputs['tuning']['new'] == tune and inputs['tuning_pairs'] == tuning_pairs, 'new fitting/pair manifests changed')
    for panel in ('earlier', 'temporal'):
        require(inputs['tuning'][panel] == read_ref(manifest['tuning_inputs'][panel]), 'historical retention tuning labels changed')
    training_audit, tuning_audit = verify_pairs(train, pairs), verify_pairs(tune, tuning_pairs)
    require((training_audit['pairs'], tuning_audit['pairs']) == (192, 48)
        and not set(training_audit['case_groups']) & set(tuning_audit['case_groups']), 'declared training/tuning meaning pairs or case disjointness differ')
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    parsed, _ = mixed._splits(inputs['training'], [r for panel in ('earlier', 'temporal', 'new') for r in inputs['tuning'][panel]])
    require(len(parsed) == 2736, 'complete independently parsed source-copy fitting records required')
    return {'training_pairs': training_audit, 'tuning_pairs': tuning_audit,
        'historical_rows': 2352, 'new_rows': 384, 'total_training_rows': 2736,
        'explicit_coordinate_and_trigger_labels_validated': True, 'historical_replay_and_tuning_preserved': True}


def audit_exposure(inputs, single_targets, document_targets, evidence):
    """Independent role masking after all fresh compiler evidence is frozen."""
    from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as historical_corpus
    exposure, ledger = evidence['exposure_audit'], evidence['annotation_ledger']
    require(exposure['schema'] == 'legal-clause-consistency-exposure/v1'
        and ledger['schema'] == 'legal-clause-consistency-annotations/v1', 'post-build exposure/annotation schemas differ')
    manifest = inputs['manifest']; bm = read_ref(manifest['inputs']['boundary_corpus'])
    pm = read_ref(bm['inputs']['previous_corpus']); expected_refs = historical_corpus.known_pool_references(pm)
    for panel, key in (('train', 'new_training_targets'), ('tuning', 'tuning_targets'), ('fresh', 'fresh_targets')):
        expected_refs['exposed_recent_boundary_' + panel + '_clauses'] = {'reference': bm['artifacts'][key], 'representation': 'document_clauses'}
    for name, artifact in (('new_consistency_train', 'new_training'), ('new_consistency_tuning', 'new_tuning')):
        expected_refs[name] = {'reference': manifest['artifacts'][artifact], 'representation': 'annotated_single'}
    require(exposure['known_pool_references'] == expected_refs, 'exposure pool references differ from pinned manifest ancestry')
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
            require(representation in ('annotated_single', 'grounding_single'), 'closed exposure representation required')
        if 'filter_domain' in metadata: rows = [r for r in rows if r['domain'] == metadata['filter_domain']]
        pools[name] = rows
    layouts = {name: {retained.independent_layout(row) for row in rows} for name, rows in pools.items()}
    require(exposure['known_pool_counts'] == {k: len(v) for k, v in pools.items()}
        and exposure['known_role_masked_layouts'] == {k: sorted(v) for k, v in layouts.items()}, 'independent local layout inventory differs')
    annotations = {r['id']: r for r in ledger['single_rows']}
    require(len(annotations) == len(ledger['single_rows']) == 624, 'complete single annotation inventory required')
    group_sets = {}; fresh_groups = {}; families = set(manifest['fresh_families'])
    for panel, rows in (('train', inputs['new_train']), ('tuning', inputs['tuning']['new']), ('fresh', single_targets['fresh'])):
        group_sets[panel] = set()
        for row in rows:
            a = annotations[row['id']]
            require(a['panel'] == panel and a['source_sha256'] == boundary.text_sha(row['source_text'])
                and a['facet_spans'] == row['facet_spans'] and a['trigger_span'] == row['trigger_span'], 'source/coordinate annotation binding differs')
            group_sets[panel].add(a['case_group'])
            if panel == 'fresh': fresh_groups.setdefault(a['case_group'], []).append(row)
        if panel != 'fresh':
            for pair in inputs['training_pairs'] if panel == 'train' else inputs['tuning_pairs']:
                left, right = annotations[pair['left_id']], annotations[pair['right_id']]
                require(left['case_group'] == right['case_group'] == pair['case_group']
                    and left['meaning_group'] == right['meaning_group'], 'semantic pair crosses authored case or meaning group')
    require(len(fresh_groups) == 36 and len(families) == 4 and all(len(rows) == 4
        and len({digest(r['canonical_ir']) for r in rows}) == 1
        and {annotations[r['id']]['family'] for r in rows} == families for rows in fresh_groups.values()),
        'fresh36 cases must retain four distinct rendering families with identical targets')
    single_evidence = []
    for row in single_targets['fresh']:
        a = annotations[row['id']]; shape = retained.independent_layout(row)
        matches = sorted(name for name, values in layouts.items() if shape in values)
        require(matches == [], 'fresh single repeats a pinned local role layout')
        single_evidence.append({'id': row['id'], 'source_sha256': boundary.text_sha(row['source_text']),
            'role_masked_layout': shape, 'matching_pools': matches, 'case_group': a['case_group'], 'family': a['family']})
    doc_annotations = {r['candidate_id']: r for r in ledger['document_rows']}
    documents = document_targets['fresh_documents']; group_sets['document'] = {r['case_group'] for r in doc_annotations.values()}
    require(len(doc_annotations) == len(ledger['document_rows']) == len(documents) == len(group_sets['document']) == 96
        and set(doc_annotations) == {r['candidate_id'] for r in documents}, 'complete unique fresh document case inventory required')
    for document in documents:
        a = doc_annotations[document['candidate_id']]
        require(a['source_sha256'] == document['source_sha256'] and a['supported'] is document['supported']
            and len(a['clause_coordinates']) == len(document['clauses']), 'fresh document annotation source/occurrences differ')
        for index, (coord, clause) in enumerate(zip(a['clause_coordinates'], document['clauses'])):
            require(coord['clause_index'] == index and coord['char_start'] == clause['char_start'] and coord['char_end'] == clause['char_end']
                and coord['family'] == a['family'] == document['construction'], 'fresh document clause family/interval differs')
            for field, span in coord['facet_spans'].items():
                value = clause['rule'][field]
                atom = (value[0] if value else None) if field in ('conditions', 'exceptions', 'temporal') else value
                require((span is None) is (atom is None) and (span is None or clause['char_start'] <= span[0] < span[1] <= clause['char_end']
                    and document['source_text'][span[0]:span[1]] == atom), 'fresh document facet occurrence differs')
    require(all(not group_sets[a] & group_sets[b] for i, a in enumerate(group_sets) for b in list(group_sets)[i + 1:]),
            'fitting/tuning/fresh/document case groups overlap')
    document_evidence = []
    for row in retained.document_audit_clauses(documents):
        shape = retained.independent_layout(row); matches = sorted(name for name, values in layouts.items() if shape in values)
        require(matches == [], 'fresh document clause repeats a pinned local role layout')
        document_evidence.append({'id': row['id'], 'source_sha256': boundary.text_sha(row['source_text']),
            'role_masked_layout': shape, 'matching_pools': matches})
    cue_families = {'where': ('single_where_front', 'single_where_suffix'), 'save where': ('single_save_where_suffix',),
        'except where': ('single_except_where_front', 'single_except_where_suffix'), 'in cases where': ('single_in_cases_front', 'single_in_cases_suffix'),
        'except in cases where': ('single_except_cases_postmodal',)}
    cue_rows = {cue: [r['id'] for r in inputs['new_train'] if annotations[r['id']]['family'] in cue_families[cue]
        and sum(bool(r['canonical_ir']['rules'][0][f]) for f in ('conditions', 'exceptions', 'temporal')) == 1]
        for cue in manifest['new_lexical_cues']}
    require(single_evidence == exposure['single_rows'] and document_evidence == exposure['document_clause_rows']
        and len(document_evidence) == manifest['counts']['document_supported_clause_occurrences']
        and cue_rows == exposure['lexical_cue_training_rows'] and all(cue_rows.values()), 'post-build exposure evidence or lexical training support differs')
    return {'known_pool_references': expected_refs, 'known_pool_counts': {k: len(v) for k, v in pools.items()},
        'fresh_single_rows': 144, 'fresh_single_case_groups': 36, 'fresh_variants_per_case': 4,
        'fresh_document_sources': 96, 'fresh_supported_clause_occurrences': len(document_evidence),
        'lexical_cue_training_rows': cue_rows, 'training_case_groups': len(group_sets['train']), 'tuning_case_groups': len(group_sets['tuning']),
        'fresh_local_layout_matches': 0, 'canonical_pair_and_fresh_variant_semantics_verified': True,
        'local_role_masked_layout_holdout_verified': True, 'universal_language_or_statutory_generalization_claimed': False}


def expected_batch(seed, step, pools):
    require(type(step) is int and 1 <= step <= 800, 'bounded additional optimizer step required')
    indices = {}
    for name in ('earlier', 'historical_new', 'pairs'):
        selected = []
        for position in range((step - 1) * 3, step * 3):
            epoch, cursor = divmod(position, len(pools[name]))
            order = list(range(len(pools[name])))
            random.Random(f'clause-consistency/v1:{seed}:{name}:{epoch}').shuffle(order)
            selected.append(order[cursor])
        indices[name] = selected
    pairs = [pools['pairs'][i] for i in indices['pairs']]
    return {'optimizer_step': step, 'indices_by_pool': indices,
        'ids': [pools[name][i] for name in ('earlier', 'historical_new') for i in indices[name]] + [identity for pair in pairs for identity in pair],
        'pairs': pairs}


def verify_training_report(report, preceding, checkpoint, inputs):
    start, finish = preceding['progress']['optimizer_steps'], checkpoint['progress']['optimizer_steps']
    config, model_config = checkpoint['training_config'], checkpoint['model_config']
    objective = config['objective']; enabled = model_config['trigger_enabled']; weight = .25 if objective == 'consistency' else 0.
    require(finish - start == report['optimizer_steps'] == 400 and report['new_optimizer_steps_total'] == finish
        and report['training_executed'] is True and report['stopped_reason'] == 'step_limit'
        and report['tuning_used_for_fit'] is False and report['objective'] == objective,
        'complete fixed400-update training stage with fitting-only labels required')
    require(report['checkpoint_sha256'] == digest(checkpoint)
        and report['mixed_parent_checkpoint_sha256'] == checkpoint['mixed_parent_checkpoint_sha256']
        and report['mixed_parent_optimizer_steps'] == checkpoint['mixed_parent_optimizer_steps'] == 800,
        'training report checkpoint or temporal800 parent binding differs')
    require(len(report['batch_losses']) == len(report['batch_loss_components']) == len(report['batch_exposures']) == 400
        and report['domain_exposures'] == {'earlier': 1200, 'new': 3600} and report['pair_exposures'] == 1200,
        'complete3+3+3pair stage exposures required')
    require(type(report['elapsed_seconds']) in (int, float) and math.isfinite(report['elapsed_seconds']) and report['elapsed_seconds'] > 0
        and math.isfinite(report['gradient_norm_max']) and report['gradient_norm_max'] >= 0,
        'finite training timing and gradient receipts required')
    pools = {'earlier': [r['id'] for r in inputs['replay']['earlier']],
        'historical_new': [r['id'] for name in ('prior_new', 'temporal') for r in inputs['replay'][name]],
        'pairs': [[r['left_id'], r['right_id']] for r in inputs['training_pairs']]}
    numerical = ('semantic', 'trigger', 'actor', 'semantic_earlier', 'semantic_new', 'actor_earlier', 'actor_new',
        'js_modality', 'js_presence', 'js_endpoints', 'base_ce', 'consistency_js', 'weighted_consistency', 'total')
    def close(a, b): return math.isclose(a, b, rel_tol=2e-5, abs_tol=2e-6)
    for step, (exposure, parts, loss) in enumerate(zip(report['batch_exposures'], report['batch_loss_components'], report['batch_losses']), start + 1):
        require(exposure == expected_batch(config['seed'], step, pools), 'independent objective-neutral paired minibatch order differs')
        require(parts['domain_rows'] == {'earlier': 3, 'new': 9} and parts['supervised_trigger_rows'] == 9
            and parts['trigger_loss_rows'] == (9 if enabled else 0) and parts['pair_count'] == 3
            and parts['consistency_weight'] == weight, 'domain, trigger mask or paired loss counts differ')
        require(all(type(parts[k]) in (int, float) and math.isfinite(parts[k]) and parts[k] >= -2e-6 for k in numerical)
            and type(loss) in (float, int) and math.isfinite(loss) and loss >= -2e-6, 'finite bounded loss components required')
        require(all(parts[k] <= math.log(2) + 2e-6 for k in ('js_modality', 'js_presence', 'js_endpoints', 'consistency_js')),
                'Jensen-Shannon divergence exceeds probability bound')
        require(close(parts['semantic'], (parts['semantic_earlier'] + parts['semantic_new']) / 2)
            and close(parts['actor'], (parts['actor_earlier'] + parts['actor_new']) / 2)
            and close(parts['base_ce'], parts['semantic'] + model_config['trigger_loss_weight'] * parts['trigger'] + model_config['actor_loss_weight'] * parts['actor'])
            and close(parts['consistency_js'], sum(parts[k] for k in ('js_modality', 'js_presence', 'js_endpoints')) / 3)
            and close(parts['weighted_consistency'], weight * parts['consistency_js'])
            and close(parts['total'], parts['base_ce'] + parts['weighted_consistency']) and close(loss, parts['total']),
            'independent CE/three-component JS/weighted total accounting differs')
        if not enabled:
            require(all(parts[k] == 0 for k in ('actor', 'trigger', 'actor_earlier', 'actor_new')), 'disabled auxiliary losses must be zero')
    gradients = report['auxiliary_gradient_norm_max']
    require(set(gradients) == {'trigger_boundary', 'trigger_modality', 'actor_boundary'}
        and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in gradients.values()), 'finite auxiliary gradient inventory required')
    if not enabled:
        require(all(v == 0 for v in gradients.values()), 'disabled auxiliary gradients must remain zero')
        for name, value in preceding['model_state'].items():
            if name.startswith(('trigger_boundary.', 'trigger_modality.', 'actor_boundary.')):
                require(checkpoint['model_state'][name] == value, 'disabled auxiliary parameters changed')
    changed = [name for name, value in checkpoint['model_state'].items() if value != preceding['model_state'][name]]
    require(changed and len(report['changed_parameter_names']) == len(changed)
        and sorted(report['changed_parameter_names']) == sorted(changed), 'changed model tensor inventory differs')
    return {'additional_steps_before': start, 'additional_steps_after': finish, 'optimizer_updates': 400,
        'domain_exposures': report['domain_exposures'], 'pair_exposures': 1200,
        'batch_trace_sha256': digest(report['batch_exposures']), 'same_semantics_pairs_only': True,
        'independent_schedule_and_loss_accounting_verified': True, 'optimizer_trajectory_replayed': False}


def objective_sanity():
    """Independently evaluate probability arithmetic; no optimizer or decoder run."""
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as runtime
    torch.set_num_threads(1)
    present = [True, True, True, False, True, False]
    records = [
        {'tokens': list(range(9)), 'trigger_span': [1, 1], 'labels': {'modality': 0, 'presence': present,
            'spans': [(0, 0), (2, 2), (4, 4), (-100, -100), (6, 6), (-100, -100)]}},
        {'tokens': list(range(11)), 'trigger_span': [3, 3], 'labels': {'modality': 0, 'presence': present,
            'spans': [(5, 5), (1, 1), (7, 7), (-100, -100), (0, 0), (-100, -100)]}}]
    def roles(record):
        values = [7] * len(record['tokens'])
        for facet, span in enumerate(record['labels']['spans']):
            if record['labels']['presence'][facet]:
                for token in range(span[0], span[1] + 1): values[token] = facet
        for token in range(record['trigger_span'][0], record['trigger_span'][1] + 1): values[token] = 6
        return values
    def project(logits, record):
        probabilities = torch.softmax(logits[:len(record['tokens'])], dim=0)
        values = roles(record)
        return torch.stack([sum((probabilities[i] for i, role in enumerate(values) if role == bucket), probabilities.sum() * 0)
                            for bucket in range(8)])
    def js(p, q):
        middle = (p + q) / 2
        return ((torch.xlogy(p, p / middle.clamp_min(1e-12))).sum(-1)
                + (torch.xlogy(q, q / middle.clamp_min(1e-12))).sum(-1)) / 2
    rng = torch.Generator().manual_seed(83617)
    output = {key: torch.randn(shape, generator=rng, dtype=torch.float64, requires_grad=True)
        for key, shape in (('modality', (2, 3)), ('presence', (2, 4, 2)), ('start', (2, 6, 13)), ('end', (2, 6, 13)))}
    for row, record in enumerate(records):
        require(runtime._role_buckets(torch, record).tolist() == roles(record), 'role bucket membership differs')
        for facet in range(6):
            require(torch.allclose(runtime._project(torch, output['start'][row, facet], record), project(output['start'][row, facet], record), atol=1e-12, rtol=1e-12),
                    'independent token probability projection differs')
    actual, parts = runtime._consistency_loss(torch, output, records, ((0, 1),))
    expected_parts = {'js_modality': js(output['modality'][0].softmax(-1), output['modality'][1].softmax(-1)),
        'js_presence': js(output['presence'][0].softmax(-1), output['presence'][1].softmax(-1)).mean(),
        'js_endpoints': torch.stack([js(project(output[key][0, facet], records[0]), project(output[key][1, facet], records[1]))
            for facet in range(6) if present[facet] for key in ('start', 'end')]).mean()}
    require(set(parts) == set(expected_parts) and all(torch.allclose(parts[k], v, atol=1e-12, rtol=1e-12) for k, v in expected_parts.items())
        and torch.allclose(actual, sum(expected_parts.values()) / 3, atol=1e-12, rtol=1e-12), 'equal three-component projected JS differs')
    actual.backward()
    require(all(tensor.grad is not None and all(float(tensor.grad[row].abs().sum()) > 0 for row in (0, 1)) for tensor in output.values()),
            'consistency must differentiate both pair sides')
    require(all(float(output[key].grad[:, facet].abs().sum()) == 0 for key in ('start', 'end') for facet in (3, 5))
        and all(float(output[key].grad[row, :, len(record['tokens']):].abs().sum()) == 0 for key in ('start', 'end') for row, record in enumerate(records)),
        'absent facets and padded tokens must not receive endpoint JS gradients')
    aligned = {key: torch.zeros_like(tensor.detach()) for key, tensor in output.items()}
    for row, record in enumerate(records):
        bucket = roles(record); counts = Counter(bucket); included = sorted(counts)
        for index, role in enumerate(bucket):
            probability = 1 / len(included) / counts[role]
            aligned['start'][row, :, index] = math.log(probability)
            aligned['end'][row, :, index] = math.log(probability)
        aligned['start'][row, :, len(bucket):] = 500.
        aligned['end'][row, :, len(bucket):] = -500.
    zero, _ = runtime._consistency_loss(torch, aligned, records, ((0, 1),))
    require(abs(float(zero)) < 1e-12, 'role-equivalent token permutations should have zero projected JS')
    aligned['start'][:, 3] = 100.; aligned['end'][:, 5] = -100.
    absent, _ = runtime._consistency_loss(torch, aligned, records, ((0, 1),))
    require(abs(float(absent)) < 1e-12, 'absent facet endpoint logits entered JS')
    aligned['modality'][1, 1] = 5.
    changed, _ = runtime._consistency_loss(torch, aligned, records, ((0, 1),))
    require(float(changed) > 0, 'unequal modality probabilities must create positive JS')
    p, q = torch.tensor([1., 0.], dtype=torch.float64), torch.tensor([0., 1.], dtype=torch.float64)
    require(math.isclose(float(runtime._js(torch, p, q)), math.log(2), abs_tol=1e-12)
        and float(runtime._js(torch, p, p)) == 0, 'JS identity or maximum probability bound differs')
    return {'independent_probability_projection_verified': True, 'equal_three_component_mean_verified': True,
        'paired_source_order_and_padding_invariance_verified': True, 'absent_endpoint_exclusion_verified': True,
        'both_pair_sides_have_gradients': True, 'js_identity_and_log2_bound_verified': True,
        'main_span_heads_only': True, 'auxiliary_boundaries_in_js': False,
        'sample_component_values': {k: float(v.detach()) for k, v in parts.items()},
        'optimizer_executed': False, 'decoder_inference_executed': False}


def tuning_audit(fields, item, inputs, frozen, label):
    """Recompute all gate metrics with independent complete-source scoring."""
    jobs, normalized = [], {}
    for panel in ('earlier', 'temporal', 'new'):
        reference = fields['tuning_' + panel]; saved = read_ref(reference)
        sources = inputs['sources']['tuning_' + panel]
        metric = previous.score(saved['generation']['rows'], sources, inputs['tuning'][panel])
        require(saved['metrics'] == metric and fields['tuning_' + panel + '_exact'] == metric['exact'], 'independent single tuning counts differ')
        normalized[panel] = metric['exact']
        jobs.append({'kind': 'single', 'name': label + '/tuning_' + panel, 'model': item, 'sources': sources,
            'generation': reference, 'stage': True})
    for policy in ('parent', 'expanded'):
        reference = fields['document_tuning_' + policy]; saved = read_ref(reference)
        sources = inputs['document_sources']['document_tuning']
        metric = retained.score_documents(saved['generation'], sources, inputs['document_tuning'])
        require(saved['metrics'] == metric and fields['tuning_document_' + policy + '_exact'] == metric['exact']
            and fields['tuning_document_' + policy + '_unsupported_accepted'] == metric['unsupported_accepted'],
            'independent canonical AND occurrence document tuning counts differ')
        normalized['document_' + policy] = metric['exact']; normalized['guard_' + policy] = metric['unsupported_accepted']
        head = 'parent' if policy == 'parent' else f"expanded-{item['seed']}"
        jobs.append({'kind': 'document', 'name': label + '/document_tuning_' + policy, 'model': item, 'sources': sources,
            'generation': reference, 'boundary': frozen['boundaries'][head]['document_tuning'], 'stage': True})
    return jobs, normalized


def verify_training(inputs, frozen, selection):
    from scripts.ops.legal_ir import run_legal_clause_consistency_experiment as runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as runtime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    require(selection['executed_optimizer_updates'] == 9600 and selection['fresh_targets_opened'] is selection['regression_targets_opened'] is False,
            'complete pre-reference fitting freeze required')
    trials = selection['trials']; models = {m['name']: m for m in frozen['models']}
    require(len(trials) == 12 and {(r['objective'], r['architecture'], r['seed']) for r in trials} ==
        {(o, a, s) for o in OBJECTIVES for a in ARCHITECTURES for s in SEEDS}, 'all12 objective/architecture/seed trials required')
    parent_tuning = read_ref(selection['parent_tuning']); jobs, audits, parents = [], [], {}
    tuning = [r for panel in ('earlier', 'temporal', 'new') for r in inputs['tuning'][panel]]
    pairs = [[p['left_id'], p['right_id']] for p in inputs['training_pairs']]
    require(inputs['runtime_pairs'] == pairs, 'runtime pair index list differs from annotated meaning pairs')
    expected_parent_names = {f'parent_{a}-{s}' for a in ARCHITECTURES for s in SEEDS}
    require(set(parent_tuning) == expected_parent_names, 'all six parent tuning references required')
    for name in sorted(expected_parent_names):
        model = models[name]; parent_ref = inputs['parents'][(model['architecture'], model['seed'])]['checkpoint']
        require(model['checkpoint'] == model['parent'] == parent_ref, 'unchanged temporal800 parent checkpoint differs')
        local_jobs, metric = tuning_audit(parent_tuning[name], model, inputs, frozen, 'parent-reference-' + name)
        jobs.extend(local_jobs); parents[name] = {k: metric[k] for k in ('earlier', 'temporal', 'document_parent', 'document_expanded')}
        for panel in ('earlier', 'temporal', 'new'):
            require(read_ref(parent_tuning[name]['tuning_' + panel])['generation'] == read_ref(frozen['files'][name]['tuning_' + panel]),
                    'parent reference and selected single tuning outputs differ')
        for policy in ('parent', 'expanded'):
            require(read_ref(parent_tuning[name]['document_tuning_' + policy])['generation'] == read_ref(frozen['document_files'][name + '__' + policy]['document_tuning']),
                    'parent reference and selected document tuning outputs differ')
    for trial in trials:
        name, seed, architecture, objective = (trial[k] for k in ('name', 'seed', 'architecture', 'objective'))
        require(trial == models[name] and trial['executed_steps'] == 800 and trial['enabled'] is (architecture == 'grounding')
            and trial['fresh_targets_opened'] is trial['regression_targets_opened'] is False,
            'trial identity/architecture/budget differs')
        require({k: v for k, v in trial.items() if k != 'selection_record'} == read_ref(trial['selection_record']), 'trial selection record differs')
        parent_name = f'parent_{architecture}-{seed}'; parent_ref = models[parent_name]['checkpoint']
        require(trial['parent'] == parent_ref and trial['parent_tuning'] == parent_tuning[parent_name], 'same-architecture/seed parent tuning anchor differs')
        parent = mixed.load_checkpoint(parent_ref['path'], expected_sha256=parent_ref['sha256'])
        require(parent['progress']['optimizer_steps'] == 800 and parent['config']['seed'] == seed
            and parent['config']['trigger_enabled'] is trial['enabled'], 'frozen temporal800 parent architecture differs')
        initial = runtime.load_checkpoint(trial['initial_checkpoint']['path'], expected_sha256=trial['initial_checkpoint']['sha256'])
        reconstructed = runtime.build_checkpoint(parent, inputs['training'], tuning, pairs, objective=objective, seed=seed, learning_rate=.001, batch_size=12)
        require(initial == reconstructed and initial['model_state'] == parent['model_state']
            and initial['optimizer_state'] == {'schema': 'adam-default-betas-eps/v1', 'parameters': {}}
            and initial['progress']['optimizer_steps'] == 0 and trial['initial_model_state_sha256'] == digest(parent['model_state']),
            'copied pretrained tensors/fresh Adam/complete initialization reconstruction differs')
        initialization = read_ref(trial['initialization'])
        require(initialization['parent'] == parent_ref and initialization['initial'] == trial['initial_checkpoint']
            and initialization['initial_model_state_sha256'] == initialization['parent_model_state_sha256'] == digest(parent['model_state'])
            and initialization['parent_tuning'] == parent_tuning[parent_name]
            and initialization['all_initial_tensors_equal'] is initialization['all_tuning_numerical_predictions_equal'] is initialization['optimizer_reset'] is True
            and initialization['historical_optimizer_resumed'] is False, 'initialization provenance or optimizer reset receipt differs')
        for panel in ('earlier', 'temporal', 'new'):
            a = read_ref(initialization['parent_tuning']['tuning_' + panel]); b = read_ref(initialization['tuning']['tuning_' + panel])
            require(a['generation']['rows'] == b['generation']['rows'] and a['metrics'] == b['metrics'], 'initial source predictions/logits changed')
            require(all(report['checkpoint_sha256'] == digest(initial) for report in b['generation']['reports']), 'initial inference checkpoint metadata differs')
        for policy in ('parent', 'expanded'):
            a = read_ref(initialization['parent_tuning']['document_tuning_' + policy]); b = read_ref(initialization['tuning']['document_tuning_' + policy])
            require(runner.document_signature(a['generation']) == runner.document_signature(b['generation']) and a['metrics'] == b['metrics'],
                    'initial learned-boundary pipeline predictions changed')
        require([s['steps'] for s in trial['stages']] == [400, 800], 'complete400/800 candidate inventory required')
        previous_checkpoint = initial; normalized, stages = [], []
        for stage in trial['stages']:
            checkpoint = runtime.load_checkpoint(stage['checkpoint']['path'], expected_sha256=stage['checkpoint']['sha256'])
            require(stage['previous_checkpoint_sha256'] == checkpoint['parent_checkpoint_sha256'] == digest(previous_checkpoint)
                and checkpoint['progress']['optimizer_steps'] == stage['steps'], 'checkpoint/optimizer resumption chain differs')
            for field in ('schema', 'lineage_id', 'implementation', 'mixed_parent_checkpoint', 'mixed_parent_checkpoint_sha256',
                'mixed_parent_optimizer_steps', 'model_config', 'training_config', 'initial_model_state_sha256',
                'training_manifest_sha256', 'tuning_manifest_sha256', 'pair_manifest_sha256', 'training_count', 'tuning_count', 'pool_counts'):
                require(checkpoint[field] == initial[field], 'stage fitting provenance changed: ' + field)
            report = read_ref(stage['training_report'])
            report_audit = verify_training_report(report, previous_checkpoint, checkpoint, inputs)
            item = {**trial, 'checkpoint': stage['checkpoint'], 'decoder_kind': 'consistency'}
            local_jobs, scores = tuning_audit(stage, item, inputs, frozen, name + f"/stage-{stage['steps']}")
            jobs.extend(local_jobs); normalized.append({'steps': stage['steps'], **scores})
            wanted_eligible = all(scores[k] >= parents[parent_name][k] - 1 for k in parents[parent_name]) and scores['guard_parent'] == scores['guard_expanded'] == 0
            require(stage['eligible'] is wanted_eligible, 'recorded multi-panel retention eligibility differs')
            stages.append({**report_audit, 'checkpoint': stage['checkpoint'], 'training_report': stage['training_report'],
                'tuning': scores, 'eligible': wanted_eligible})
            previous_checkpoint = checkpoint
        chosen = selection_choice(normalized, parents[parent_name])
        steps = chosen['steps'] if chosen else 0
        checkpoint_ref = next(s['checkpoint'] for s in trial['stages'] if s['steps'] == steps) if chosen else parent_ref
        status = 'candidate' if chosen else 'parent_fallback_no_acceptable_replacement'
        require(trial['selected_steps'] == steps and trial['checkpoint'] == checkpoint_ref and trial['selection'] == status
            and trial['decoder_kind'] == ('consistency' if chosen else 'mixed'), 'independent tuning-only candidate/fallback choice differs')
        chosen_fields = next(s for s in trial['stages'] if s['steps'] == steps) if chosen else parent_tuning[parent_name]
        for panel in ('earlier', 'temporal', 'new'):
            require(read_ref(chosen_fields['tuning_' + panel])['generation'] == read_ref(frozen['files'][name]['tuning_' + panel]), 'selected single tuning differs from chosen stage')
        for policy in ('parent', 'expanded'):
            require(read_ref(chosen_fields['document_tuning_' + policy])['generation'] == read_ref(frozen['document_files'][name + '__' + policy]['document_tuning']),
                    'selected document tuning differs from chosen stage')
        audits.append({'name': name, 'objective': objective, 'architecture': architecture, 'seed': seed, 'parent': parent_ref,
            'initial_checkpoint': trial['initial_checkpoint'], 'initial_model_state_sha256': digest(parent['model_state']),
            'stages': stages, 'parent_tuning': parents[parent_name], 'selection': status, 'selected_steps': steps,
            'checkpoint': checkpoint_ref, 'executed_optimizer_updates': 800,
            'historical_optimizer_resumed': False, 'optimizer_trajectory_replayed': False})
    by_name = {r['name']: r for r in trials}; matched = []
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            ce, consistency = (by_name[f'{objective}_{architecture}-{seed}'] for objective in OBJECTIVES)
            require(ce['parent'] == consistency['parent'] and ce['initial_model_state_sha256'] == consistency['initial_model_state_sha256'],
                    'paired objectives copied different model tensors')
            batches = []
            for a, b in zip(ce['stages'], consistency['stages']):
                left, right = read_ref(a['training_report']), read_ref(b['training_report'])
                require(left['batch_exposures'] == right['batch_exposures'], 'CE/consistency minibatch order differs')
                batches.extend(left['batch_exposures'])
            require(len(batches) == 800, 'full800 objective-matched batch schedule required')
            matched.append({'architecture': architecture, 'seed': seed, 'parent': ce['parent'],
                'initial_model_state_sha256': ce['initial_model_state_sha256'], 'batch_count': 800,
                'batch_exposures_sha256': digest(batches), 'identical_batch_order': True})
    require(selection['matched_objective_audit'] == matched, 'matched objective exposure receipt differs')
    return jobs, audits, matched


def verify_protocol(plan, inputs, frozen):
    require(plan['objectives'] == list(OBJECTIVES) and plan['architectures'] == list(ARCHITECTURES)
        and plan['seeds'] == list(SEEDS) and plan['additional_stage_steps'] == [400, 800]
        and plan['additional_updates_per_trial'] == 800 and plan['total_optimizer_updates'] == 9600
        and plan['optimizer'] == 'Adam' and plan['learning_rate'] == .001 and plan['optimizer_reset'] is True
        and plan['historical_optimizer_resumed'] is False and plan['batch_size'] == 12
        and plan['batch_quota'] == {'earlier': 3, 'historical_new': 3, 'new_pairs': 3, 'new_pair_rows': 6}
        and plan['consistency_weight'] == .25 and plan['identical_pair_objective_batch_order_required'] is True
        and plan['inference_changed'] is plan['joint_search_enabled'] is False
        and plan['threads_per_worker'] == 1 and 1 <= plan['workers'] <= 3
        and plan['single_counts'] == SINGLE_COUNTS and plan['document_counts'] == DOCUMENT_COUNTS
        and plan['boundary_heads'] == inputs['boundary_heads'] and plan['retention_tolerance'] == 1
        and plan['unsupported_acceptance_tolerance'] == 0
        and plan['fresh_targets_opened'] is plan['regression_targets_opened'] is False,
        'predeclared matched consistency protocol differs')
    read_ref(inputs['config']['study_design'], parse=False)
    for pipeline in frozen['pipelines']:
        require(pipeline['boundary_checkpoint'] == inputs['boundary_heads'][pipeline['boundary_head']]['checkpoint'],
                'pipeline changed frozen boundary checkpoint')


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_clause_consistency_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1 <= args.workers <= 3, 'one to three CPU replay workers required')
    folder, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    frozen_ref = ref(folder / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == runner.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['fresh_targets_opened'] is frozen['regression_targets_opened'] is False
        and frozen['executed_optimizer_updates'] == 9600 and frozen['boundary_optimizer_updates'] == 0
        and frozen['training_executed'] is True, 'complete fixed-budget source-only training/generation freeze required')
    plan = read_ref(frozen['plan'])
    require(all(sha(path) == wanted for path, wanted in plan['producer_pins'].items()), 'frozen training implementation drift')
    read_ref(plan['config'], parse=False); inputs = runner.load_config(plan['config']['path'])
    require(read_ref(frozen['sources']) == inputs['sources'] and read_ref(frozen['document_sources']) == inputs['document_sources']
        and read_ref(frozen['heads']) == frozen['models'] and read_ref(frozen['pipeline_heads']) == frozen['pipelines'],
        'frozen source/model/pipeline inventories differ')
    inventory = verify_inventory(frozen['models'], frozen['pipelines'], frozen['files'], frozen['document_files'], inputs['boundary_heads'], frozen['boundaries'])
    verify_protocol(plan, inputs, frozen)
    output.mkdir(parents=True, exist_ok=False)
    pins = dict(plan['producer_pins'])
    for module in (sys.modules[__name__], runner, corpus, runtime, retained, retained.prior, retained.calendar,
        retained.calendar_summary, retained.compose, boundary_qualification, boundary_qualification.attribution,
        boundary_qualification.boundary_audit, clauses, boundary, previous, gate):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    fitting = verify_fitting(inputs); sanity = objective_sanity()
    selection = read_ref(frozen['selections'])
    jobs, training_audits, matched = verify_training(inputs, frozen, selection)
    require(frozen['parent_fallbacks'] == [r['name'] for r in selection['trials'] if r['selection'] != 'candidate'], 'parent fallback inventory differs')
    training_ref = write(output / 'training-and-selection-audit.json', {'schema': SCHEMA, 'selections': frozen['selections'],
        'fitting': fitting, 'objective_sanity': sanity, 'trials': training_audits, 'matched_objective_batches': matched,
        'executed_optimizer_updates': 9600, 'boundary_optimizer_updates': 0,
        'initial_numerical_predictions_equal_verified_against_replayed_parent': True, **FALSE})
    for name, head in inputs['boundary_heads'].items():
        for panel, reference in frozen['boundaries'][name].items():
            jobs.append({'kind': 'boundary', 'name': name + '/' + panel, 'checkpoint': head['checkpoint'],
                'sources': inputs['document_sources'][panel], 'generation': reference})
    singles, documents = {}, {}
    for model in frozen['models']:
        name = model['name']; singles[name] = {}
        for panel, reference in frozen['files'][name].items():
            singles[name][panel] = read_ref(reference)
            require(len(singles[name][panel]['rows']) == SINGLE_COUNTS[panel], 'selected single inference dropped sources')
            jobs.append({'kind': 'single', 'name': name + '/' + panel, 'model': model, 'sources': inputs['sources'][panel], 'generation': reference})
    for pipeline in frozen['pipelines']:
        name = pipeline['name']; documents[name] = {}
        for panel, reference in frozen['document_files'][name].items():
            documents[name][panel] = read_ref(reference)
            require(len(documents[name][panel]['rows']) == DOCUMENT_COUNTS[panel], 'selected pipeline inference dropped documents')
            jobs.append({'kind': 'document', 'name': name + '/' + panel, 'model': pipeline,
                'sources': inputs['document_sources'][panel], 'generation': reference,
                'boundary': frozen['boundaries'][pipeline['boundary_head']][panel]})
    require(sum(len(j['sources']) for j in jobs if j.get('stage')) == 15120
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'single') == 18144
        and sum(len(j['sources']) for j in jobs if not j.get('stage') and j['kind'] == 'document') == 13824
        and sum(len(j['sources']) for j in jobs if j['kind'] == 'boundary') == 1536, 'complete replay denominators differ')
    replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(replay_job, job) for job in jobs]):
            value = future.result(); replays.append(value)
            print({'phase': 'replayed', 'kind': value['kind'], 'panel': value['name'], 'rows': value['rows']}, flush=True)
    for i, left in enumerate(frozen['models']):
        for right in frozen['models'][i + 1:]:
            if left['checkpoint'] == right['checkpoint'] and left['decoder_kind'] == right['decoder_kind']:
                require(singles[left['name']] == singles[right['name']], 'duplicate selected checkpoint single outputs differ')
                if left['seed'] == right['seed']:
                    require(all(documents[left['name'] + '__' + p] == documents[right['name'] + '__' + p] for p in ('parent', 'expanded')),
                            'duplicate selected checkpoint document outputs differ')
    replay_ref = write(output / 'replay-frozen.json', {'schema': SCHEMA, 'generation_freeze': frozen_ref,
        'training_and_selection_audit': training_ref, 'panels': sorted(replays, key=lambda r: r['name']),
        'single_rows': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_rows': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'boundary_rows': sum(r['rows'] for r in replays if r['kind'] == 'boundary'),
        'stage_and_parent_tuning_rows': 15120, 'selected_single_rows': 18144, 'selected_document_rows': 13824,
        'fresh_and_regression_targets_opened': False, 'reference_derived_layout_evidence_opened': False, **FALSE})
    single_selections, document_selections = {}, {}
    for model in frozen['models']:
        name = model['name']; sources = inputs['sources']['fresh']; predictions = singles[name]['fresh']['rows']
        selected = retained.calendar.select_candidates(sources, predictions, toolchain=args.toolchain, policy=retained.calendar.POLICY)
        lookup = {s['id']: (s, p) for s, p in zip(sources, predictions)}
        for entry in selected['rows']:
            retained.calendar_summary.verify_entry(*lookup[entry['candidate']['candidate_id']], entry)
        require(selected['source_count'] == len(selected['rows']) + len(selected['excluded']) == 144, 'fresh single build selection dropped sources')
        single_selections[name] = selected
    for pipeline in frozen['pipelines']:
        name = pipeline['name']
        document_selections[name] = retained.document_selection(documents[name]['fresh_documents']['rows'],
            inputs['document_sources']['fresh_documents'], toolchain=args.toolchain)
    build_selection_ref = write(output / 'build-selection-frozen.json', {'schema': SCHEMA,
        'single': single_selections, 'document': document_selections, 'replay': replay_ref,
        'single_source_slots': 2592, 'document_source_slots': 3456,
        'canonical_references_used_for_selection': False, 'fresh_targets_opened': False,
        'interpretation_policy': retained.calendar.POLICY})
    builds = {'single': {}, 'document': {}}
    for kind, selections in (('single', single_selections), ('document', document_selections)):
        for name, selected in selections.items():
            builds[kind][name] = retained.build_batches(selected['rows'], output / 'builds' / kind / name, args)
            print({'phase': 'built', 'kind': kind, 'model': name, 'supported_for_lowering': len(selected['rows'])}, flush=True)
    builds_ref = write(output / 'builds-frozen.json', {'schema': SCHEMA, **builds, 'selections': build_selection_ref,
        'replay': replay_ref, 'fresh_and_regression_targets_opened': False, 'reference_derived_layout_evidence_opened': False, **FALSE})
    # Fresh/regression targets and coordinate-derived role layouts first open here.
    config, manifest = inputs['config'], inputs['manifest']
    single_target_refs = {'fresh': manifest['artifacts']['challenge_targets'],
        **{panel: config[panel + '_targets'] for panel in ('prior_construction', 'earlier_regression', 'temporal_regression')}}
    single_targets = {'tuning_' + panel: inputs['tuning'][panel] for panel in ('earlier', 'temporal', 'new')}
    for panel, reference in single_target_refs.items():
        single_targets[panel] = previous.reference_rows(read_ref(reference), inputs['sources'][panel])
    document_target_refs = {'fresh_documents': manifest['artifacts']['document_challenge_targets'],
        'prior_boundary_documents': config['prior_boundary_document_targets'], 'exposed_documents': config['exposed_document_targets']}
    document_targets = {'document_tuning': inputs['document_tuning']}
    for panel, reference in document_target_refs.items():
        document_targets[panel] = read_ref(reference)
        require(clauses.source_rows(document_targets[panel]) == inputs['document_sources'][panel], 'post-build document source/reference binding differs')
    evidence_refs = {key: manifest['artifacts'][key] for key in ('annotation_ledger', 'exposure_audit')}
    evidence = {key: read_ref(reference) for key, reference in evidence_refs.items()}
    exposure_ref = write(output / 'construction-exposure-audit.json', audit_exposure(inputs, single_targets, document_targets, evidence))
    boundary_metrics = {name: {panel: boundary_qualification.score_boundaries(read_ref(reference), inputs['document_sources'][panel], document_targets[panel])
        for panel, reference in panels.items()} for name, panels in frozen['boundaries'].items()}
    single_metrics, document_metrics, model_reports, pipeline_reports = {}, {}, [], []
    for model in frozen['models']:
        name = model['name']
        single_metrics[name] = {panel: single_error_metrics(value, inputs['sources'][panel], single_targets[panel], enabled=model['enabled'])
            for panel, value in singles[name].items()}
        exact = {r['id']: r['exact'] for r in single_metrics[name]['fresh']['rows']}
        build_metric = retained.prior.build_accounting(single_selections[name], builds['single'][name], exact)
        model_reports.append({**model, 'single_metrics': {p: {k: v for k, v in metric.items() if k not in ('rows', 'error_rows')}
            for p, metric in single_metrics[name].items()}, 'single_builds': build_metric})
    for pipeline in frozen['pipelines']:
        name = pipeline['name']; document_metrics[name] = {}
        for panel, generation in documents[name].items():
            b = boundary_metrics[pipeline['boundary_head']][panel]
            if panel == 'fresh_documents':
                metric = boundary_qualification.pipeline_funnel(generation, b, inputs['document_sources'][panel], document_targets[panel],
                    document_selections[name], builds['document'][name])
            else:
                measured = retained.score_documents(generation, inputs['document_sources'][panel], document_targets[panel])
                references = {r['candidate_id']: r for r in document_targets[panel]}; boundaries = {r['id']: r for r in b['rows']}
                rows = [boundary_qualification.attribution.pipeline_record(r, references[r['candidate_id']], boundaries[r['candidate_id']]) for r in generation['rows']]
                metric = {'metrics': {k: v for k, v in measured.items() if k != 'rows'}, 'rows': rows,
                    'attribution': boundary_qualification.attribution.pipeline_counts(rows), 'native_build_not_executed_on_this_panel': True}
            document_metrics[name][panel] = metric
        pipeline_reports.append({**pipeline, 'panels': {panel: {k: v for k, v in value.items() if k != 'rows'} for panel, value in document_metrics[name].items()}})
    single_totals, document_totals = {}, {}
    for objective in POLICIES:
        for architecture in ARCHITECTURES:
            arm = objective + '_' + architecture; group = [m for m in model_reports if m['arm'] == arm]
            single_totals[arm] = {'panels': {panel: {key: sum(m['single_metrics'][panel][key] for m in group)
                for key in ('count', 'decoded', 'abstained', 'exact')} for panel in SINGLE_COUNTS},
                'builds': {key: sum(m['single_builds'][key] for m in group)
                    for key in ('count', 'built', 'built_exact', 'built_reference_mismatch', 'build_invocations')}}
            for policy in ('parent', 'expanded'):
                pipeline_arm = arm + '__' + policy; pipelines = [p for p in pipeline_reports if p['arm'] == pipeline_arm]
                document_totals[pipeline_arm] = {'panels': {panel: {key: sum(p['panels'][panel]['metrics'][key] for p in pipelines)
                    for key in ('count', 'supported', 'unsupported', 'composed', 'abstained', 'exact', 'decision_exact',
                        'canonical_rule_list_exact', 'occurrence_boundaries_exact', 'unsupported_accepted')} for panel in DOCUMENT_COUNTS},
                    'builds': {key: sum(p['panels']['fresh_documents']['builds'][key] for p in pipelines)
                        for key in pipelines[0]['panels']['fresh_documents']['builds']}}
    details_ref = write(output / 'scored-details.json', {'single': single_metrics, 'document': document_metrics, 'boundary': boundary_metrics})
    require(all(sha(path) == wanted for path, wanted in pins.items()), 'qualifier or producer source drift')
    require(runner.load_config(plan['config']['path']) == inputs, 'frozen fitting/source input closure changed')
    for reference in [frozen_ref, frozen['plan'], frozen['sources'], frozen['document_sources'], frozen['heads'], frozen['pipeline_heads'], frozen['selections'],
        *single_target_refs.values(), *document_target_refs.values(), *evidence_refs.values(),
        *[r for panels in frozen['files'].values() for r in panels.values()], *[r for panels in frozen['document_files'].values() for r in panels.values()],
        *[r for panels in frozen['boundaries'].values() for r in panels.values()]]:
        read_ref(reference, parse=False)
    result = {'schema': SCHEMA, 'generation_freeze': frozen_ref, 'training_and_selection_audit': training_ref,
        'replay': replay_ref, 'builds': builds_ref, 'details': details_ref, 'construction_exposure_audit': exposure_ref,
        'reference_single': single_target_refs, 'reference_documents': document_target_refs, 'posthoc_evidence': evidence_refs,
        'models': model_reports, 'pipelines': pipeline_reports, 'single_totals': single_totals, 'document_totals': document_totals,
        'producer_pins': pins, 'parent_fallbacks': frozen['parent_fallbacks'], 'executed_optimizer_updates': 9600,
        'boundary_optimizer_updates': 0, 'inventory': inventory,
        'single_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'single'),
        'document_inference_rows_replayed': sum(r['rows'] for r in replays if r['kind'] == 'document'),
        'boundary_source_documents_replayed': sum(r['rows'] for r in replays if r['kind'] == 'boundary'),
        'clause_occurrences_replayed': sum(r.get('clause_occurrences_replayed', 0) for r in replays),
        'actual_lake_build_invocations': sum(b['backend_executed'] for selections in builds.values() for batches in selections.values() for b in batches),
        'build_attempts': sum(len(batches) for selections in builds.values() for batches in selections.values()),
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes': True,
        'reference_derived_novelty_evidence_opened_after_build_freeze': True,
        'test_results_used_for_selection_or_gate_revision': False,
        'scope': 'Matched CE/role-projected consistency continuation; restricted authored flat deontic/calendar profile. Native compiler success is distinct from source/reference fidelity.',
        **FALSE}
    write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'single_totals': single_totals, 'document_totals': document_totals}, flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--lake-executable', required=True); parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    parser.add_argument('--workers', type=int, default=3)
    run(parser.parse_args())
