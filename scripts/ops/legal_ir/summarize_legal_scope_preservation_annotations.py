"""Pure post-release audit of new evaluation annotations and unchanged prior TRAIN.

All values are supplied by the qualification caller after replay/build freeze.
No file I/O, fitting, inference, statutory labels, or nested-logic targets.
"""
from collections import Counter
import random
from scripts.ops.legal_ir import summarize_legal_scope_adapter_annotations as adapter

boundary, require, normalize = adapter.boundary, adapter.require, adapter.normalize
HEADINGS, TIME_KINDS, FACTORS, SOURCE_KEYS = adapter.HEADINGS, adapter.TIME_KINDS, adapter.FACTORS, adapter.SOURCE_KEYS
COUNTS = {'tuning': 96, 'fresh': 192}
SHUFFLE_SEED = 904173


def audit_scope_annotations(inputs, fresh_targets, fresh_pairs, ledger, exposure, *,
    historical_documents, prior_annotation_ledgers, historical_source_inventory,
    historical_manifests, prior_training_pairs):
    from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs
    require(set(historical_manifests) == {'prior_scope','prior_condition','prior_adapter','prior_adapter_config'},
        'four pinned prior manifest/config values required')
    old_scope, old_condition, old_adapter, old_config = (historical_manifests[k] for k in
        ('prior_scope','prior_condition','prior_adapter','prior_adapter_config'))
    manifest = inputs['manifest']
    require(manifest['schema'] == 'authored-legal-scope-preservation-corpus/v1'
        and manifest['training_reused_without_changes'] is True and manifest['new_training_documents'] == 0
        and manifest['training_documents'] == 1152, 'unchanged TRAIN preservation manifest required')
    require(old_config['scope_corpus_manifest'] == manifest['inputs']['prior_adapter_corpus'], 'prior adapter config binding differs')
    expected_retention = {**old_adapter['retention_target_references'], **old_config['additional_tuning_refs'],
        'prior_adapter_tuning': old_adapter['artifacts']['tuning_targets'],
        'prior_adapter_fresh': old_adapter['artifacts']['fresh_targets']}
    require(manifest['retention_target_references'] == expected_retention and len(expected_retention) == 17,
        'all previously admitted retention references required')
    require(manifest['replay_references'] == old_adapter['replay_references']
        and all(manifest['artifacts'][k] == old_adapter['artifacts'][k]
            for k in ('new_training_targets','training_pairs','training_sources')), 'prior training references changed')
    expected_refs = {**old_scope['replay_references'], 'prior_scope': old_scope['artifacts']['new_training_targets'],
        **old_scope['retention_target_references'], 'prior_scope_tuning': old_scope['artifacts']['tuning_targets'],
        'prior_scope_exposed_fresh': old_scope['artifacts']['fresh_targets'],
        'condition_document_tuning': old_condition['artifacts']['document_tuning_targets'],
        'condition_exposed_documents': old_condition['artifacts']['document_challenge_targets'],
        'prior_adapter_train': old_adapter['artifacts']['new_training_targets'],
        'prior_adapter_tuning': old_adapter['artifacts']['tuning_targets'],
        'prior_adapter_fresh': old_adapter['artifacts']['fresh_targets']}
    require(set(historical_documents) == set(expected_refs)
        and all(historical_documents[k]['reference'] == pin for k, pin in expected_refs.items()),
        'complete exact historical document ancestry required')
    require(inputs['new_train'] == historical_documents['prior_adapter_train']['rows']
        and len(inputs['new_train']) == 384, 'prior384 TRAIN row content/order changed')
    require(prior_training_pairs['reference'] == old_adapter['artifacts']['training_pairs']
        and inputs['training_pairs'] == prior_training_pairs['rows'], 'prior192 training pair content/order changed')
    require(set(inputs['replay']) == set(old_adapter['replay_references'])
        and all(rows == historical_documents[name]['rows'] for name, rows in inputs['replay'].items())
        and sum(map(len, inputs['replay'].values())) == 768, 'prior768 replay content/order changed')
    require(len(inputs['tuning']) == 18 and sum(map(len, inputs['tuning'].values())) == 1872
        and set(inputs['tuning']) == set(expected_retention) | {'scope_new'}, 'all18 tuning panels/1872 rows required')
    for name, pin in expected_retention.items():
        candidates = [v['rows'] for v in historical_documents.values() if v['reference'] == pin]
        require(candidates and inputs['tuning'][name] == candidates[0], 'retention content/order changed: ' + name)
    verify_scope_pairs(inputs['new_train'], inputs['training_pairs'], 192)
    panels = {'tuning': inputs['tuning']['scope_new'], 'fresh': fresh_targets}
    pair_panels = {'tuning': inputs['tuning_pairs'], 'fresh': fresh_pairs}
    require({p:len(v) for p,v in panels.items()} == COUNTS, 'all288 new evaluation documents required')
    require(set(ledger) == {'schema','document_rows'} and ledger['schema'] == 'legal-scope-preservation-annotations/v1',
        'preservation annotation schema differs')
    annotations = {a['candidate_id']: a for a in ledger['document_rows']}
    require(len(annotations) == len(ledger['document_rows']) == 288
        and set(annotations) == {r['candidate_id'] for rows in panels.values() for r in rows}, 'complete unique evaluation annotation rows required')
    require([{k:r[k] for k in SOURCE_KEYS} for r in fresh_targets] == inputs['sources']['scope_fresh']
        and all(set(r) == SOURCE_KEYS for r in inputs['sources']['scope_fresh']), 'complete opaque source-only order/content join differs')
    layouts, audits, source_sets, meaning_sets, case_sets = {}, {}, {}, {}, {}
    for panel, rows in panels.items():
        audit = verify_scope_pairs(rows, pair_panels[panel], len(rows)//2)
        labels = [annotations[r['candidate_id']] for r in rows]
        layouts[panel] = {r['candidate_id']: adapter.audit_document(r, annotations[r['candidate_id']], panel) for r in rows}
        for pair in pair_panels[panel]:
            left,right = (annotations[pair[k]] for k in ('independent_id','nested_id'))
            require(left['case_group'] == right['case_group'] == pair['case_group'] and left['factors'] == right['factors'],
                'paired case/factor binding differs')
            require([o['source_text'] for o in left['local_clause_coordinates']] == [o['source_text'] for o in right['local_clause_coordinates']]
                and [o['rule'] for o in left['local_clause_coordinates']] == [o['rule'] for o in right['local_clause_coordinates']],
                'scope contrast changes local bodies or meanings')
        for key, values in (('first_modality','OPF'),('heading',HEADINGS),('child_time_kind',TIME_KINDS),
                            ('clause_count',(2,3)),('first_CE_mask',range(4))):
            for side in (True,False):
                require(Counter(str(a['factors'][key]) for a in labels if a['supported'] is side)
                    == {str(v):len(rows)//(2*len(values)) for v in values}, 'per-class factor margin differs: '+key)
        crossed = {tuple(a['factors'][k] for k in ('first_modality','heading','child_time_kind','clause_count')) for a in labels}
        require(len(crossed) == 48, 'all48 modality/heading/time/clause-count combinations required')
        literal_counts = {k:sum(v in r['source_text'] for r in rows) for k,v in HEADINGS.items()}
        require(literal_counts == {k:len(rows)//2 for k in HEADINGS}, 'realized heading balance differs')
        unshuffled = [a['candidate_id'] for a in ledger['document_rows'] if a['panel'] == panel]
        random.Random(SHUFFLE_SEED + list(COUNTS).index(panel)).shuffle(unshuffled)
        require(unshuffled == [r['candidate_id'] for r in rows], 'class-neutral source order shuffle differs')
        source_sets[panel] = {normalize(r['source_text']) for r in rows}
        meaning_sets[panel] = {boundary.digest(o['rule']) for a in labels for o in a['local_clause_coordinates']}
        case_sets[panel] = set(audit['cases'])
        require(len(source_sets[panel]) == len(rows), 'within-panel source duplication')
        audits[panel] = {**audit, 'heading_literals':literal_counts,
            'factor_counts': {k:dict(Counter(str(a['factors'][k]) for a in labels)) for k in sorted(FACTORS)},
            'local_occurrences':sum(len(a['local_clause_coordinates']) for a in labels),
            'max_source_tokens':max(len(boundary.tokenize(r['source_text'])) for r in rows)}
    require(not(source_sets['tuning'] & source_sets['fresh'] or meaning_sets['tuning'] & meaning_sets['fresh']
        or case_sets['tuning'] & case_sets['fresh']), 'new source/meaning/case split overlap')
    require(set(prior_annotation_ledgers) == {'prior_scope','prior_adapter'}, 'two exact prior annotation bundles required')
    old_annotations, adapter_annotations = {}, {}
    for key, source, schema, dest in (
        ('prior_scope',old_scope,'legal-scope-retention-annotations/v1',old_annotations),
        ('prior_adapter',old_adapter,'legal-scope-adapter-annotations/v1',adapter_annotations)):
        bundle = prior_annotation_ledgers[key]
        require(bundle['reference'] == source['artifacts']['annotation_ledger'] and bundle['ledger']['schema'] == schema,
            'prior annotation pin/schema differs')
        for a in bundle['ledger']['document_rows']:
            require(a['candidate_id'] not in dest, 'duplicate old annotations'); dest[a['candidate_id']] = a
    old_layout_rows, skipped, old_texts_from_docs, old_meanings, old_cases = {}, {}, set(), set(), set()
    for name,item in historical_documents.items():
        old_layout_rows[name], skipped[name] = [], []
        for row in item['rows']:
            old_texts_from_docs.add(normalize(row['source_text']))
            old_meanings.update(boundary.digest(c['rule']) for c in row['clauses'])
            identity = row['candidate_id']
            if identity in adapter_annotations:
                a = adapter_annotations[identity]; layout = adapter.audit_document(row,a,a['panel']); old_cases.add(a['case_group'])
            elif identity in old_annotations:
                a = old_annotations[identity]; layout = adapter.previous.audit_document(row,a,a['panel']); old_cases.add(a['case_group'])
            else: layout = adapter.historical_flat_layout(row)
            if layout is None: skipped[name].append(identity)
            else: old_layout_rows[name].append({'candidate_id':identity,'source_sha256':row['source_sha256'],'role_masked_layout':layout})
    known = {p:sorted({r['role_masked_layout'] for r in rows}) for p,rows in old_layout_rows.items()}
    known['new_tuning'] = sorted(set(layouts['tuning'].values()))
    require(exposure['schema'] == 'legal-scope-preservation-exposure/v1'
        and exposure['historical_document_references'] == expected_refs
        and exposure['prior_scope_annotation_reference'] == prior_annotation_ledgers['prior_scope']['reference']
        and exposure['prior_adapter_annotation_reference'] == prior_annotation_ledgers['prior_adapter']['reference']
        and exposure['historical_layout_rows'] == old_layout_rows
        and exposure['historical_unannotated_unsupported_ids'] == skipped
        and exposure['known_role_masked_layouts'] == known, 'historical exposure reconstruction differs')
    expected_rows = []
    for row in fresh_targets:
        identity=row['candidate_id']; layout=layouts['fresh'][identity]
        matches=sorted(k for k,values in known.items() if layout in values)
        expected_rows.append({'candidate_id':identity,'source_sha256':row['source_sha256'],
            'case_group':annotations[identity]['case_group'],'role_masked_layout':layout,'matching_pools':matches,
            'layout_status':'matched_audited_layout' if matches else 'unmatched_audited_combination'})
    require(exposure['rows'] == expected_rows, 'all192 fresh layout matches differ')
    old_texts = {normalize(t) for t in historical_source_inventory['source_texts']}
    require(old_texts_from_docs <= old_texts and exposure['historical_source_inventory_count'] == len(old_texts)
        and exposure['historical_source_inventory_sha256'] == boundary.digest(sorted(old_texts)), 'complete old source commitment differs')
    require(exposure['prior_source_references'] == historical_source_inventory['prior_source_references']
        and exposure['prior_condition_single_references'] == historical_source_inventory['condition_single_references']
        == {k:old_condition['artifacts'][k] for k in ('new_tuning','challenge_targets')}
        and exposure['real_exposed_views'] == historical_source_inventory['real_exposed_views'] == 86,
        'old source inventory ancestry differs')
    require(not old_texts & set.union(*source_sets.values()) and not old_meanings & set.union(*meaning_sets.values())
        and not old_cases & set.union(*case_sets.values()) and exposure['new_source_overlap_count'] == 0,
        'new evaluation source/meaning/case overlaps history')
    require(exposure['training_reused_without_new_examples'] is True, 'unchanged TRAIN exposure declaration required')
    return {'schema':'legal-scope-preservation-independent-annotation-audit/v1','panels':audits,
        'new_evaluation_documents':288,'new_scope_pairs':144,'unchanged_training_documents':1152,
        'unchanged_paired_training_documents':384,'unchanged_training_pairs':192,
        'prior_training_content_order_and_reference_binding_verified':True,
        'direct_source_role_and_scope_annotations_verified':True,'source_hash_ids_have_no_explicit_class_fields':True,
        'class_neutral_source_order_shuffle_verified':True,'all_previous_challenges_are_exposed_retention':True,
        'historical_layout_counts':{k:len(v) for k,v in old_layout_rows.items()},
        'historical_unsupported_without_role_annotations':{k:len(v) for k,v in skipped.items()},
        'fresh_layout_counts':dict(Counter(r['layout_status'] for r in expected_rows)),
        'fresh_matching_reused_training_layout':sum('prior_adapter_train' in r['matching_pools'] for r in expected_rows),
        'historical_source_and_supported_meaning_overlap':0,'helper_opens_files':False,'statutory_gold_available':False,
        'limits':['Shared authored factor grammar; new entity/case/source holdout does not imply unseen constructions.',
            'Old unsupported documents without role annotations supply source exclusions, not layout novelty evidence.',
            'Nested control local roles are author-stipulated; no nested logic target or statutory semantic validity is claimed.']}
