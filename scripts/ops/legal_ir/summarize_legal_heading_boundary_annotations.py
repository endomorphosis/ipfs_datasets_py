"""Pure independent audit of heading layouts and TRAIN-only boundary masks.

All values are supplied by the qualification caller after replay/build freeze.
No file I/O, fitting, inference, statutory labels, or nested-logic targets.
"""
from collections import Counter
from copy import deepcopy
import re
import random
from scripts.ops.legal_ir import summarize_legal_scope_adapter_annotations as adapter

boundary, require, normalize = adapter.boundary, adapter.require, adapter.normalize
TIME_KINDS, FACTORS, SOURCE_KEYS = adapter.TIME_KINDS, adapter.FACTORS, adapter.SOURCE_KEYS
HEADINGS={'numbered_colon':'(2) Filing duty: ','bracket_colon':'Filing duty [2]: ',
    'stacked_marker':'[2]\nFiling duty.—\n','nested_markers':'Filing duty (2)(A): ',
    'caption_after_time':'[Filing duty] [2]. ','split_citation':'Filing [§13.2] duty: '}
FAMILIES_BY_PANEL={'tuning':('numbered_colon','bracket_colon'),
    'fresh':('stacked_marker','nested_markers','caption_after_time','split_citation')}
ROLE_KEYS={'candidate_id','source_sha256','true_end_token_indices','editorial_hard_negative_token_indices','editorial_heading_spans','provenance'}
COUNTS = {'tuning': 96, 'fresh': 192}
SHUFFLE_SEED = 914173


def heading_structure(occurrence):
    result=[]
    for note in occurrence['editorial_context']:
        pattern=[]
        for text in re.findall(r"\w+|[^\w\s]",note['source_text']):
            mark='#' if text.isdigit() else 'H' if re.fullmatch(r"\w+",text) else text
            if mark!='H' or not pattern or pattern[-1]!='H':pattern.append(mark)
        temporal=occurrence['facet_spans']['temporal']
        placement='absent' if temporal is None else ('before_heading' if temporal[1]<=note['start_char'] else 'after_heading')
        result.append({'marker_pattern':' '.join(pattern),'temporal_relative_order':placement})
    return result


def audit_document(row,annotation,panel):
    require(set(annotation)==adapter.previous.ANNOTATION_KEYS|{'factors'},'closed heading annotation required')
    factors=annotation['factors']
    require(set(factors)==FACTORS and factors['heading'] in FAMILIES_BY_PANEL[panel]
        and annotation['family']==factors['heading'],'declared split-specific heading factor required')
    require(row['candidate_id']=='scope-'+adapter.text_sha(row['source_text'])
        and row['construction']==(annotation['family'] if row['supported'] else 'unsupported/nested_normative_exception'),
        'opaque source identity or construction differs')
    legacy={k:deepcopy(v) for k,v in annotation.items() if k!='factors'};legacy['family']='numbered_child'
    layout=adapter.previous.audit_document({**row,'construction':'numbered_child' if row['supported'] else row['construction']},legacy,panel)
    occurrences=annotation['local_clause_coordinates'];first=occurrences[0]['rule']
    require(len(occurrences)==factors['clause_count'] in (2,3) and factors['first_modality']==first['modality']
        and factors['first_CE_mask']==int(bool(first['conditions']))+2*int(bool(first['exceptions'])), 'source factor roles differ')
    child=occurrences[1];notes=child['editorial_context']
    require(len(notes)==1 and notes[0]['source_text']==HEADINGS[factors['heading']], 'heading literal differs')
    note=notes[0];time=child['rule']['temporal'];span=child['facet_spans']['temporal'];kind=factors['child_time_kind']
    if not time:
        require(kind=='none' and span is None and note['start_char']==child['char_start'],'absent time/heading order differs')
    else:
        patterns={'days':r'within \d+ days','hours':r'within \d+ hours','calendar':r'before \d{4}-\d{2}-\d{2}'}
        require(kind in patterns and len(time)==1 and re.fullmatch(patterns[kind],time[0])
            and span[1]<child['facet_spans']['actor'][0],'exact leading temporal form differs')
        if factors['heading']=='caption_after_time':
            require(span[0]==child['char_start'] and note['start_char']==span[1]+2,'time-before-heading source order differs')
        else:require(note['start_char']==child['char_start'] and span[0]==note['end_char'],'heading-before-time source order differs')
    require(len(boundary.tokenize(row['source_text']))<=512 and not boundary.UNSUPPORTED.search(row['source_text']), 'bounded unchanged-profile source required')
    return layout


def audit_training_token_roles(inputs,prior_annotation_ledgers):
    manifest=inputs['manifest'];refs={k:prior_annotation_ledgers[k]['reference'] for k in ('prior_scope','prior_adapter')}
    require(manifest['training_annotation_references']==refs,'training-mask authorial provenance differs')
    replay=[r for rows in inputs['replay'].values() for r in rows]
    full=replay+inputs['new_train'];supported=[r for r in full if r['supported']]
    require(len(full)==1152 and len(supported)==720 and sum(not r['supported'] for r in full)==432,
        'complete inventory with720supported/432excluded required')
    require(inputs['boundary_training']==supported and len(inputs['training_token_roles'])==720,
        'unsupported or extra source entered token supervision')
    expected_by_id={a['candidate_id']:a for k in ('prior_scope','prior_adapter')
        for a in prior_annotation_ledgers[k]['ledger']['document_rows']}
    positive_count=negative_count=headings=0
    for row,record in zip(supported,inputs['training_token_roles'],strict=True):
        require(set(record)==ROLE_KEYS and record['candidate_id']==row['candidate_id']
            and record['source_sha256']==row['source_sha256'] and record['provenance']=='pinned_train_endpoints_and_optional_editorial_spans/v1',
            'closed supported TRAIN-only token-mask record differs')
        source=row['source_text'];tokens=boundary.tokenize(source);ends={c['char_end'] for c in row['clauses']}
        wanted_positive=[i for i,t in enumerate(tokens) if t['char_end'] in ends]
        require(len(wanted_positive)==len(ends),'gold clause ends not token aligned')
        spans=[];a=expected_by_id.get(row['candidate_id'])
        if a is not None:
            # Validate old authored roles before trusting editorial ownership.
            if 'factors' in a:adapter.audit_document(row,a,a['panel'])
            else:adapter.previous.audit_document(row,a,a['panel'])
            spans=sorted(({'char_start':n['start_char'],'char_end':n['end_char']}
                for o in a['local_clause_coordinates'] for n in o['editorial_context']),key=lambda n:(n['char_start'],n['char_end']))
        require(record['editorial_heading_spans']==spans,'TRAIN heading spans differ from pinned authorial annotations')
        negatives=[i for i,t in enumerate(tokens) if re.fullmatch(r'[^\w\s]',t['text']) and i not in wanted_positive
            and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in spans)]
        require(record['true_end_token_indices']==wanted_positive and record['editorial_hard_negative_token_indices']==negatives,
            'TRAIN exact endpoints or complete punctuation-negative mask differs')
        positive_count+=len(wanted_positive);negative_count+=len(negatives);headings+=bool(spans)
    require((positive_count,negative_count,headings)==(1824,864,240),'fixed TRAIN mask coverage differs')
    return {'supervised_documents':720,'unsupported_documents_excluded':432,'true_end_tokens':positive_count,
        'editorial_punctuation_negative_tokens':negative_count,'heading_bearing_documents':headings,
        'direct_prior_TRAIN_annotation_spans_independently_verified':True,'prediction_based_mining_used':False}


def audit_heading_annotations(inputs, fresh_targets, fresh_pairs, ledger, exposure, *,
    historical_documents, prior_annotation_ledgers, historical_source_inventory,
    historical_manifests, prior_training_pairs):
    from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs
    require(set(historical_manifests) == {'prior_scope','prior_condition','prior_adapter','prior_adapter_config','prior_preservation'},
        'five pinned prior manifest/config values required')
    old_scope, old_condition, old_adapter, old_config, old_preservation = (historical_manifests[k] for k in
        ('prior_scope','prior_condition','prior_adapter','prior_adapter_config','prior_preservation'))
    manifest = inputs['manifest']
    require(manifest['schema'] == 'authored-legal-heading-boundary-corpus/v1'
        and manifest['training_reused_without_changes'] is True and manifest['new_training_documents'] == 0
        and manifest['training_documents'] == 1152, 'unchanged TRAIN preservation manifest required')
    require(old_config['scope_corpus_manifest'] == old_preservation['inputs']['prior_adapter_corpus'], 'prior adapter config binding differs')
    expected_retention = {**old_preservation['retention_target_references'],
        'prior_preservation_tuning':old_preservation['artifacts']['tuning_targets'],
        'prior_preservation_fresh':old_preservation['artifacts']['fresh_targets']}
    require(manifest['retention_target_references'] == expected_retention and len(expected_retention) == 19,
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
        'prior_adapter_fresh': old_adapter['artifacts']['fresh_targets'],
        'prior_preservation_tuning':old_preservation['artifacts']['tuning_targets'],
        'prior_preservation_fresh':old_preservation['artifacts']['fresh_targets']}
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
    require(len(inputs['tuning']) == 20 and sum(map(len, inputs['tuning'].values())) == 2160
        and set(inputs['tuning']) == set(expected_retention) | {'heading_new'}, 'all20 tuning panels/2160 rows required')
    for name, pin in expected_retention.items():
        candidates = [v['rows'] for v in historical_documents.values() if v['reference'] == pin]
        require(candidates and inputs['tuning'][name] == candidates[0], 'retention content/order changed: ' + name)
    verify_scope_pairs(inputs['new_train'], inputs['training_pairs'], 192)
    panels = {'tuning': inputs['tuning']['heading_new'], 'fresh': fresh_targets}
    pair_panels = {'tuning': inputs['tuning_pairs'], 'fresh': fresh_pairs}
    require({p:len(v) for p,v in panels.items()} == COUNTS, 'all288 new evaluation documents required')
    require(set(ledger) == {'schema','document_rows'} and ledger['schema'] == 'legal-heading-boundary-annotations/v1',
        'preservation annotation schema differs')
    annotations = {a['candidate_id']: a for a in ledger['document_rows']}
    require(len(annotations) == len(ledger['document_rows']) == 288
        and set(annotations) == {r['candidate_id'] for rows in panels.values() for r in rows}, 'complete unique evaluation annotation rows required')
    require([{k:r[k] for k in SOURCE_KEYS} for r in fresh_targets] == inputs['sources']['heading_fresh']
        and all(set(r) == SOURCE_KEYS for r in inputs['sources']['heading_fresh']), 'complete opaque source-only order/content join differs')
    layouts, audits, source_sets, meaning_sets, case_sets = {}, {}, {}, {}, {}
    for panel, rows in panels.items():
        audit = verify_scope_pairs(rows, pair_panels[panel], len(rows)//2)
        labels = [annotations[r['candidate_id']] for r in rows]
        layouts[panel] = {r['candidate_id']: audit_document(r, annotations[r['candidate_id']], panel) for r in rows}
        for pair in pair_panels[panel]:
            left,right = (annotations[pair[k]] for k in ('independent_id','nested_id'))
            require(left['case_group'] == right['case_group'] == pair['case_group'] and left['factors'] == right['factors'],
                'paired case/factor binding differs')
            require([o['source_text'] for o in left['local_clause_coordinates']] == [o['source_text'] for o in right['local_clause_coordinates']]
                and [o['rule'] for o in left['local_clause_coordinates']] == [o['rule'] for o in right['local_clause_coordinates']],
                'scope contrast changes local bodies or meanings')
        for key, values in (('first_modality','OPF'),('heading',FAMILIES_BY_PANEL[panel]),('child_time_kind',TIME_KINDS),
                            ('clause_count',(2,3)),('first_CE_mask',range(4))):
            for side in (True,False):
                require(Counter(str(a['factors'][key]) for a in labels if a['supported'] is side)
                    == {str(v):len(rows)//(2*len(values)) for v in values}, 'per-class factor margin differs: '+key)
        crossed = {tuple(a['factors'][k] for k in ('first_modality','heading','child_time_kind','clause_count')) for a in labels}
        require(len(crossed) == len(rows)//2, 'complete heading/modality/time/clause-count factorial required')
        literal_counts = {k:sum(HEADINGS[k] in r['source_text'] for r in rows) for k in FAMILIES_BY_PANEL[panel]}
        require(literal_counts == {k:len(rows)//len(FAMILIES_BY_PANEL[panel]) for k in FAMILIES_BY_PANEL[panel]}, 'realized heading balance differs')
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
    require(set(prior_annotation_ledgers) == {'prior_scope','prior_adapter','prior_preservation'}, 'two exact prior annotation bundles required')
    old_annotations, adapter_annotations, preservation_annotations = {}, {}, {}
    for key, source, schema, dest in (
        ('prior_scope',old_scope,'legal-scope-retention-annotations/v1',old_annotations),
        ('prior_adapter',old_adapter,'legal-scope-adapter-annotations/v1',adapter_annotations),
        ('prior_preservation',old_preservation,'legal-scope-preservation-annotations/v1',preservation_annotations)):
        bundle = prior_annotation_ledgers[key]
        require(bundle['reference'] == source['artifacts']['annotation_ledger'] and bundle['ledger']['schema'] == schema,
            'prior annotation pin/schema differs')
        for a in bundle['ledger']['document_rows']:
            require(a['candidate_id'] not in dest, 'duplicate old annotations'); dest[a['candidate_id']] = a
    old_layout_rows, skipped, old_texts_from_docs, old_meanings, old_cases = {}, {}, set(), set(), set()
    structural_rows, heading_unannotated = {}, {}
    for name,item in historical_documents.items():
        old_layout_rows[name], skipped[name], structural_rows[name], heading_unannotated[name] = [], [], [], []
        for row in item['rows']:
            old_texts_from_docs.add(normalize(row['source_text']))
            old_meanings.update(boundary.digest(c['rule']) for c in row['clauses'])
            identity = row['candidate_id'];a=None
            if identity in preservation_annotations:
                a=preservation_annotations[identity];layout=adapter.audit_document(row,a,a['panel']);old_cases.add(a['case_group'])
            elif identity in adapter_annotations:
                a = adapter_annotations[identity]; layout = adapter.audit_document(row,a,a['panel']); old_cases.add(a['case_group'])
            elif identity in old_annotations:
                a = old_annotations[identity]; layout = adapter.previous.audit_document(row,a,a['panel']); old_cases.add(a['case_group'])
            else: layout = adapter.historical_flat_layout(row)
            if a is None:heading_unannotated[name].append(identity)
            else:
                for occurrence in a['local_clause_coordinates']:
                    for signature in heading_structure(occurrence):
                        structural_rows[name].append({'candidate_id':identity,'source_sha256':row['source_sha256'],
                            'occurrence_index':occurrence['index'],'heading_structure':signature,'heading_structure_sha256':boundary.digest(signature)})
            if layout is None: skipped[name].append(identity)
            else: old_layout_rows[name].append({'candidate_id':identity,'source_sha256':row['source_sha256'],'role_masked_layout':layout})
    known = {p:sorted({r['role_masked_layout'] for r in rows}) for p,rows in old_layout_rows.items()}
    known['new_tuning'] = sorted(set(layouts['tuning'].values()))
    structural={k:sorted({r['heading_structure_sha256'] for r in v}) for k,v in structural_rows.items()}
    structural['new_tuning']=sorted({boundary.digest(s) for r in panels['tuning'] for o in annotations[r['candidate_id']]['local_clause_coordinates'] for s in heading_structure(o)})
    require(exposure['schema'] == 'legal-heading-boundary-exposure/v1'
        and exposure['historical_document_references'] == expected_refs
        and exposure['historical_annotation_references']=={k:v['reference'] for k,v in prior_annotation_ledgers.items()}
        and exposure['historical_heading_structure_rows']==structural_rows
        and exposure['historical_heading_unannotated_ids']==heading_unannotated
        and exposure['known_heading_structure_sha256']==structural
        and exposure['historical_layout_rows'] == old_layout_rows
        and exposure['historical_unannotated_unsupported_ids'] == skipped
        and exposure['known_role_masked_layouts'] == known, 'historical exposure reconstruction differs')
    expected_rows = []
    for row in fresh_targets:
        identity=row['candidate_id']; layout=layouts['fresh'][identity]
        matches=sorted(k for k,values in known.items() if layout in values)
        signatures=[s for o in annotations[identity]['local_clause_coordinates'] for s in heading_structure(o)]
        hashes=[boundary.digest(s) for s in signatures]
        smatches=sorted(k for k,v in structural.items() if any(h in v for h in hashes))
        require(not matches and not smatches,'held-out heading structure/full layout is already exposed')
        expected_rows.append({'candidate_id':identity,'source_sha256':row['source_sha256'],
            'case_group':annotations[identity]['case_group'],'role_masked_layout':layout,'matching_pools':matches,
            'layout_status':'unmatched_audited_combination','heading_structures':signatures,
            'heading_structure_sha256':hashes,'structural_matching_pools':smatches})
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
    training_audit=audit_training_token_roles(inputs,prior_annotation_ledgers)
    return {'schema':'legal-heading-boundary-independent-annotation-audit/v1','panels':audits,'training_token_roles':training_audit,
        'new_evaluation_documents':288,'new_scope_pairs':144,'unchanged_training_documents':1152,
        'unchanged_paired_training_documents':384,'unchanged_training_pairs':192,
        'prior_training_content_order_and_reference_binding_verified':True,
        'direct_source_role_and_scope_annotations_verified':True,'source_hash_ids_have_no_explicit_class_fields':True,
        'class_neutral_source_order_shuffle_verified':True,'all_previous_challenges_are_exposed_retention':True,
        'historical_layout_counts':{k:len(v) for k,v in old_layout_rows.items()},
        'historical_unsupported_without_role_annotations':{k:len(v) for k,v in skipped.items()},
        'fresh_layout_counts':dict(Counter(r['layout_status'] for r in expected_rows)),
        'fresh_heading_structures_unmatched_after_lexical_number_whitespace_normalization':True,
        'fresh_matching_reused_training_layout':sum('prior_adapter_train' in r['matching_pools'] for r in expected_rows),
        'historical_source_and_supported_meaning_overlap':0,'helper_opens_files':False,'statutory_gold_available':False,
        'limits':['New heading punctuation/marker structures are held out against annotated inventories; clause grammar remains shared.',
            'Old unsupported documents without role annotations supply source exclusions, not layout novelty evidence.',
            'Nested control local roles are author-stipulated; no nested logic target or statutory semantic validity is claimed.']}
