#!/usr/bin/env python3
"""Author held-out heading structures and TRAIN-only token-boundary role masks.

These are source-bound authored eligibility labels, not statutory gold or targets
for nested legal logic. Previous released challenges are exposed retention data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from itertools import product
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_scope_preservation_corpus as preservation
from scripts.ops.legal_ir import prepare_legal_scope_adapter_corpus as adapter
from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as previous
from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as condition

temporal, boundary, legacy = previous.temporal, previous.boundary, previous.legacy
require, sha, file_ref, read_ref, verify_ref, write_new = (
    getattr(previous, key) for key in ('require', 'sha', 'file_ref', 'read_ref', 'verify_ref', 'write_new'))
FIELDS, SOURCE_KEYS, ROW_KEYS, PAIR_KEYS, SEALED = (
    getattr(previous, key) for key in ('FIELDS', 'SOURCE_KEYS', 'ROW_KEYS', 'PAIR_KEYS', 'SEALED'))
SCHEMA = 'authored-legal-heading-boundary-corpus/v1'
COUNTS = {'tuning': 96, 'fresh': 192}
SHUFFLE_SEED = 914173
PREFIXES = {'tuning': 'Silverheading', 'fresh': 'Goldenheading'}
HEADINGS = {'numbered_colon': '(2) Filing duty: ', 'bracket_colon': 'Filing duty [2]: ',
    'stacked_marker': '[2]\nFiling duty.—\n', 'nested_markers': 'Filing duty (2)(A): ',
    'caption_after_time': '[Filing duty] [2]. ', 'split_citation': 'Filing [§13.2] duty: '}
FAMILIES_BY_PANEL = {'tuning': ('numbered_colon','bracket_colon'),
    'fresh': ('stacked_marker','nested_markers','caption_after_time','split_citation')}
TIME_KINDS = ('none','days','hours','calendar')
FACTOR_KEYS = {'first_modality','heading','child_time_kind','clause_count','first_CE_mask'}
ROLE_KEYS = {'candidate_id','source_sha256','true_end_token_indices','editorial_hard_negative_token_indices',
    'editorial_heading_spans','provenance'}
ROLE_PROVENANCE = 'pinned_train_endpoints_and_optional_editorial_spans/v1'
DEFAULT_PRESERVATION = temporal.prior.ARTIFACTS / 'legal-decoder-scope-preservation-20261003/corpus-01/manifest.json'


def source_row(row):
    return {key: row[key] for key in sorted(SOURCE_KEYS)}


def factor_schedule(panel):
    require(panel in COUNTS, 'known evaluation panel required')
    result=[]
    for heading,modal,time,count in product(FAMILIES_BY_PANEL[panel],range(3),range(4),(2,3)):
        mask=(FAMILIES_BY_PANEL[panel].index(heading)+modal+time+count)%4
        result.append({'first_modality':'OPF'[modal],'heading':heading,'child_time_kind':TIME_KINDS[time],
            'clause_count':count,'first_CE_mask':mask})
    require(len(result)*2==COUNTS[panel], 'exact complete heading-factor denominator required')
    return result


def render_local(panel, case, ordinal, factors):
    require(panel in COUNTS and type(case) is int and 0 <= case < COUNTS[panel] // 2
        and type(ordinal) is int and 0 <= ordinal < factors['clause_count'], 'bounded local source coordinates required')
    require(set(factors) == FACTOR_KEYS and factors == factor_schedule(panel)[case], 'case/factor schedule binding differs')
    entity = f'{PREFIXES[panel]}{case:03d}x{ordinal}'
    modality = 'OPF'[('OPF'.index(factors['first_modality']) + ordinal) % 3]
    mask = factors['first_CE_mask']
    style = (mask + ordinal + TIME_KINDS.index(factors['child_time_kind'])) % 4
    trigger = temporal.TRIGGERS[modality][(case + ordinal) % 2]
    kind = factors['child_time_kind'] if ordinal == 1 else 'none'
    duration = {'none': None, 'days': f'within {17 + case % 37} days',
        'hours': f'within {23 + case % 41} hours', 'calendar': f'before 2067-04-{1 + case % 28:02d}'}[kind]
    rule = {'modality': modality, 'actor': f'the {entity} ' + ('Registry', 'Records Office', 'Dept. of Records')[ordinal],
        'action': temporal.VERBS[(case + ordinal) % len(temporal.VERBS)],
        'object': f'the {entity.lower()} filing packet',
        'conditions': [f'the {entity.lower()} permit is active'] if mask & 1 else [],
        'exceptions': [f'the {entity.lower()} exemption is active'] if mask & 2 else [],
        'temporal': [duration] if duration else []}
    writer = temporal.prior.CoordinateWriter()
    editorial, cues = [], []
    def heading():
        text=HEADINGS[factors['heading']];start=len(writer.text)
        editorial.append({'start_char':start,'end_char':start+len(text),'source_text':text,
            'author_stipulated_role':'nonoperative_editorial_context'})
        writer.add(text)
    if ordinal==1 and factors['heading']!='caption_after_time': heading()
    def facet(field):
        value = rule[field]; writer.add(value[0] if isinstance(value, list) else value, field)
    def qualifier(field, cue, suffix):
        start = len(writer.text); writer.add(cue)
        if cue: cues.append({'field': field, 'start_char': start, 'end_char': len(writer.text), 'source_text': cue})
        facet(field); writer.add(suffix)
    if duration: qualifier('temporal', '', ', ')
    if ordinal==1 and factors['heading']=='caption_after_time': heading()
    front_c = bool(rule['conditions']) and style == 0
    front_e = bool(rule['exceptions']) and style == 1
    if front_c: qualifier('conditions', 'If ' if case % 2 else 'When ', ', ')
    if front_e: qualifier('exceptions', 'Unless ', ', ')
    facet('actor')
    infix_c = bool(rule['conditions']) and style == 2
    if infix_c: qualifier('conditions', ', when ', ',')
    writer.add(' '); writer.add(trigger, 'trigger')
    post_c = bool(rule['conditions']) and style == 3
    if post_c: qualifier('conditions', ', if ' if case % 2 else ', when ', ',')
    writer.add(' '); facet('action'); writer.add(' '); facet('object')
    if rule['conditions'] and not (front_c or infix_c or post_c): qualifier('conditions', ' if ', '')
    if rule['exceptions'] and not front_e:
        qualifier('exceptions', (' unless ', ' except when ', ' except where ')[(case + ordinal) % 3], '')
    return {'source_text': writer.text, 'rule': rule, 'facet_spans': {f: writer.spans.get(f) for f in FIELDS},
        'trigger_span': writer.spans['trigger'], 'editorial_context': editorial, 'qualifier_cues': cues}


def make_pair(panel, case):
    factors = factor_schedule(panel)[case]
    local = [render_local(panel, case, i, factors) for i in range(factors['clause_count'])]
    repeated = factors['clause_count'] == 3 and case % 4 == 3
    if repeated: local[2] = deepcopy(local[0])
    group = 'case-' + sha(f'heading-boundary/{panel}/{case}'.encode())
    rows, annotations = [], []
    for supported in (True, False):
        text, occurrences, declarations, attachment = '', [], [], None
        for index, item in enumerate(local):
            if index:
                if not supported and index == 1:
                    cue = (' unless ', ' except when ', ' except where ')[case % 3]
                    start = len(text); text += cue
                    attachment = {'start_char': start, 'end_char': len(text), 'source_text': cue,
                        'parent_occurrence': 0, 'child_occurrence': 1,
                        'declared_relation': 'nested_normative_exception_outside_flat_profile'}
                else: text += '\n' if case % 2 else ' '
            start = len(text); text += item['source_text']; end = len(text)
            occurrences.append({'index': index, 'char_start': start, 'char_end': end,
                'source_text': item['source_text'], 'source_sha256': sha(item['source_text'].encode()), 'rule': deepcopy(item['rule']),
                'facet_spans': {k: [start + x for x in span] if span else None for k, span in item['facet_spans'].items()},
                'trigger_span': [start + x for x in item['trigger_span']],
                'editorial_context': [{**v, 'start_char': start + v['start_char'], 'end_char': start + v['end_char']} for v in item['editorial_context']],
                'qualifier_cues': [{**v, 'start_char': start + v['start_char'], 'end_char': start + v['end_char']} for v in item['qualifier_cues']]})
            if supported or index != 0: text += ';' if supported and index < len(local) - 1 and case % 3 == 0 else '.'
            if supported: declarations.append({'char_start': start, 'char_end': len(text), 'rule': deepcopy(item['rule'])})
        source_hash = sha(text.encode()); identity = 'scope-' + source_hash
        row = {'candidate_id': identity, 'source_text': text, 'source_sha256': source_hash,
            'supported': supported, 'construction': factors['heading'] if supported else 'unsupported/nested_normative_exception',
            'repeated_rule_occurrences': repeated if supported else False, 'clauses': declarations,
            'unsupported_reason': None if supported else 'nested_normative_exception',
            'label_origin': 'authored_scope_contrast_not_statutory_gold'}
        annotation = {'candidate_id': identity, 'source_sha256': source_hash, 'panel': panel, 'case_group': group,
            'family': factors['heading'], 'factors': deepcopy(factors), 'supported': supported,
            'side': 'independent' if supported else 'nested', 'local_clause_coordinates': occurrences,
            'scope_attachment': attachment, 'annotation_authority': 'author_stipulated_flat_profile_eligibility_not_semantic_truth'}
        validate_document(row, annotation)
        rows.append(row); annotations.append(annotation)
    pair = {'pair_id': 'pair-' + sha(group.encode()), 'case_group': group,
        'independent_id': rows[0]['candidate_id'], 'nested_id': rows[1]['candidate_id'],
        'local_clause_body_sha256': [sha(r['source_text'].encode()) for r in local]}
    return rows, pair, annotations


def validate_document(row, annotation=None):
    try:
        previous.validate_document(row, annotation)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('malformed scope source/coordinate annotation') from exc
    require(row['candidate_id'] == 'scope-' + row['source_sha256'], 'opaque exact-source identity required')
    boundary.tokenize(row['source_text'])  # Complete512-token bound; truncation is forbidden.
    if annotation is None: return
    f = annotation['factors']; local = annotation['local_clause_coordinates']
    require(set(f) == FACTOR_KEYS and annotation['family'] == f['heading'] in HEADINGS
        and len(local) == f['clause_count'] in (2, 3), 'explicit factor inventory differs')
    require(local[0]['rule']['modality'] == f['first_modality'] and f['first_modality'] in 'OPF', 'first modal factor differs')
    mask = int(bool(local[0]['rule']['conditions'])) + 2 * int(bool(local[0]['rule']['exceptions']))
    require(mask == f['first_CE_mask'], 'first C/E factor differs')
    child=local[1];notes=child['editorial_context'];wanted=f['child_time_kind'];value=child['rule']['temporal'];interval=child['facet_spans']['temporal']
    require(len(notes)==1 and notes[0]['source_text']==HEADINGS[f['heading']], 'realized heading literal differs')
    note=notes[0]
    if wanted=='none':
        require(value==[] and interval is None and note['start_char']==child['char_start'], 'absent temporal/heading placement differs')
    else:
        pattern={'days':r'within \d+ days','hours':r'within \d+ hours','calendar':r'before \d{4}-\d{2}-\d{2}'}[wanted]
        require(len(value)==1 and re.fullmatch(pattern,value[0]) and interval[1]<child['facet_spans']['actor'][0], 'temporal kind/source role differs')
        if f['heading']=='caption_after_time':
            require(interval[0]==child['char_start'] and note['start_char']==interval[1]+2, 'time-before-heading placement differs')
        else:
            require(note['start_char']==child['char_start'] and interval[0]==note['end_char'], 'heading-before-time placement differs')
    for occurrence in local:
        for note in occurrence['editorial_context']:
            require(row['source_text'][note['start_char']:note['end_char']] == note['source_text'], 'editorial exact interval differs')
        for cue in occurrence['qualifier_cues']:
            require(row['source_text'][cue['start_char']:cue['end_char']] == cue['source_text']
                and cue['end_char'] == occurrence['facet_spans'][cue['field']][0], 'qualifier cue ownership differs')


def validate_pairs(rows, pairs, expected):
    previous.validate_pairs(rows, pairs, expected)
    for row in rows: validate_document(row)


def realized_counts(rows, annotations, pair_count, panel):
    lookup = {a['candidate_id']: a for a in annotations}
    actual = {'documents': len(rows), 'supported': sum(r['supported'] for r in rows),
        'unsupported': sum(not r['supported'] for r in rows), 'scope_pairs': pair_count,
        'factors': {key: dict(Counter(str(lookup[r['candidate_id']]['factors'][key]) for r in rows)) for key in sorted(FACTOR_KEYS)},
        'heading_literals': {key: sum(HEADINGS[key] in r['source_text'] for r in rows) for key in FAMILIES_BY_PANEL[panel]},
        'max_source_tokens': max(len(boundary.tokenize(r['source_text'])) for r in rows),
        'repeated_supported_documents': sum(r['repeated_rule_occurrences'] for r in rows)}
    for key, values in (('first_modality', 'OPF'), ('heading', FAMILIES_BY_PANEL[panel]), ('child_time_kind', TIME_KINDS),
                        ('clause_count', (2, 3)), ('first_CE_mask', range(4))):
        require(actual['factors'][key] == {str(v): len(rows) // len(values) for v in values}, 'realized factor margin differs: ' + key)
    require(actual['heading_literals'] == {k: len(rows) // len(FAMILIES_BY_PANEL[panel]) for k in FAMILIES_BY_PANEL[panel]}, 'both actual heading branches must be rendered equally')
    return actual


def make_panels():
    panels, pairs, annotations, counts = {}, {}, [], {}
    for panel, count in COUNTS.items():
        rows, pairs[panel], labels = [], [], []
        for case in range(count // 2):
            pair_rows, metadata, pair_labels = make_pair(panel, case)
            rows.extend(pair_rows); pairs[panel].append(metadata); labels.extend(pair_labels)
        random.Random(SHUFFLE_SEED + list(COUNTS).index(panel)).shuffle(rows)
        validate_pairs(rows, pairs[panel], count // 2)
        counts[panel] = realized_counts(rows, labels, len(pairs[panel]), panel)
        panels[panel] = rows; annotations.extend(labels)
    normalized = [temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows]
    require(len(normalized) == len(set(normalized)) == sum(COUNTS.values()), 'new source split overlap')
    meanings = [{boundary.digest(a['rule']) for r in annotations if r['panel'] == p for a in r['local_clause_coordinates']} for p in COUNTS]
    require(not any(a & b for i, a in enumerate(meanings) for b in meanings[i + 1:]), 'local canonical meanings cross splits')
    return panels, pairs, {'schema': 'legal-heading-boundary-annotations/v1', 'document_rows': annotations}, counts


def role_layout(row, annotation):
    return previous.role_layout(row, annotation)


def historical_document_layout(row):
    """Mask supported historical flat roles only; unknown guards stay unknown."""
    if not row['supported']: return None
    locals_ = temporal.construction.document_clauses_for_audit([row])
    replacements = []
    for clause, local in zip(row['clauses'], locals_, strict=True):
        for field, span in local['facet_spans'].items():
            if span: replacements.append((clause['char_start'] + span[0], clause['char_start'] + span[1], '<' + field + '>'))
    text, cursor = '', 0
    for start, end, replacement in sorted(replacements):
        require(cursor <= start < end, 'historical role occurrence overlaps')
        text += row['source_text'][cursor:start] + replacement; cursor = end
    text += row['source_text'][cursor:]
    for cue in sorted(temporal.TRIGGER_MEANINGS, key=len, reverse=True):
        text = re.sub(r'\b' + re.escape(cue) + r'\b', '<modal>', text, flags=re.I)
    return re.sub(r'\d+', '#', ' '.join(text.casefold().split()))


def heading_structure(occurrence):
    """Normalize heading vocabulary/number identities, preserving marker order."""
    result=[]
    for note in occurrence['editorial_context']:
        pieces=[]
        for token in re.findall(r'\w+|[^\w\s]',note['source_text']):
            value='#' if token.isdigit() else 'H' if re.fullmatch(r'\w+',token) else token
            if value=='H' and pieces and pieces[-1]=='H':continue
            pieces.append(value)
        time=occurrence['facet_spans']['temporal']
        order='absent' if time is None else 'before_heading' if time[1]<=note['start_char'] else 'after_heading'
        result.append({'marker_pattern':' '.join(pieces),'temporal_relative_order':order})
    return result


def training_token_roles(rows, annotation_ledgers):
    """Derive masks from admitted supported TRAIN only, without predictions."""
    lookup={}
    for ledger in annotation_ledgers.values():
        for a in ledger['document_rows']:
            require(a['candidate_id'] not in lookup, 'duplicate annotation identity across prior producers')
            lookup[a['candidate_id']]=a
    result=[]
    for row in rows:
        require(row['supported'] is True,'unsupported rows have no boundary supervision')
        tokens=boundary.tokenize(row['source_text']);ends={c['char_end'] for c in row['clauses']}
        require(ends <= {t['char_end'] for t in tokens},'every exact endpoint must be token-aligned')
        positive=[i for i,t in enumerate(tokens) if t['char_end'] in ends]
        notes=[]
        annotation=lookup.get(row['candidate_id'])
        if annotation is not None:
            previous.validate_document(row,annotation)
            for occurrence in annotation['local_clause_coordinates']:
                for note in occurrence['editorial_context']:
                    require(note['author_stipulated_role']=='nonoperative_editorial_context'
                        and row['source_text'][note['start_char']:note['end_char']]==note['source_text'],
                        'direct authored editorial context required')
                    notes.append({'char_start':note['start_char'],'char_end':note['end_char']})
        notes.sort(key=lambda x:(x['char_start'],x['char_end']))
        negatives=[i for i,t in enumerate(tokens) if re.fullmatch(r'[^\w\s]',t['text'])
            and i not in positive and any(n['char_start']<=t['char_start']<t['char_end']<=n['char_end'] for n in notes)]
        result.append({'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],
            'true_end_token_indices':positive,'editorial_hard_negative_token_indices':negatives,
            'editorial_heading_spans':notes,'provenance':ROLE_PROVENANCE})
    return result


def role_counts(records):
    return {'documents':len(records),'true_end_tokens':sum(len(r['true_end_token_indices']) for r in records),
        'editorial_hard_negative_tokens':sum(len(r['editorial_hard_negative_token_indices']) for r in records),
        'heading_bearing_documents':sum(bool(r['editorial_heading_spans']) for r in records),
        'documents_with_auxiliary_negatives':sum(bool(r['editorial_hard_negative_token_indices']) for r in records)}


def historical_inventory(preservation_manifest_path=DEFAULT_PRESERVATION):
    parent_ref=file_ref(preservation_manifest_path);parent=read_ref(parent_ref)
    require(parent['schema']==preservation.SCHEMA,'exact prior preservation corpus required')
    history=preservation.historical_inventory(parent['inputs']['prior_adapter_corpus']['path'],parent['inputs']['prior_adapter_config']['path'])
    ledger_ref=parent['artifacts']['annotation_ledger'];ledger=read_ref(ledger_ref)
    lookup={a['candidate_id']:a for a in ledger['document_rows']}
    for name,key in (('prior_preservation_tuning','tuning_targets'),('prior_preservation_fresh','fresh_targets')):
        pin=parent['artifacts'][key];rows=read_ref(pin)
        history['document_references'][name]=pin;history['pools'][name]=rows
        history['excluded_sources'].update(r['source_text'] for r in rows)
        history['layout_rows'][name]=[{'candidate_id':r['candidate_id'],'source_sha256':r['source_sha256'],
            'role_masked_layout':role_layout(r,lookup[r['candidate_id']])} for r in rows]
        history['unannotated_unsupported_ids'][name]=[]
    history['retention_target_references']={**parent['retention_target_references'],
        'prior_preservation_tuning':parent['artifacts']['tuning_targets'],'prior_preservation_fresh':parent['artifacts']['fresh_targets']}
    require(len(history['retention_target_references'])==19,'all19 previously admitted panels required')
    history.update(prior_preservation_manifest=parent,prior_preservation_manifest_ref=parent_ref,
        prior_preservation_annotation_reference=ledger_ref)
    annotation_refs={'prior_scope':history['prior_scope_annotation_reference'],
        'prior_adapter':history['prior_adapter_annotation_reference'],'prior_preservation':ledger_ref}
    ledgers={k:read_ref(v) for k,v in annotation_refs.items()}
    all_annotations={a['candidate_id']:a for v in ledgers.values() for a in v['document_rows']}
    structures,unannotated={},{}
    for name,rows in history['pools'].items():
        structures[name],unannotated[name]=[],[]
        for row in rows:
            a=all_annotations.get(row['candidate_id'])
            if a is None:unannotated[name].append(row['candidate_id']);continue
            for occurrence in a['local_clause_coordinates']:
                for signature in heading_structure(occurrence):
                    structures[name].append({'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],
                        'occurrence_index':occurrence['index'],'heading_structure':signature,
                        'heading_structure_sha256':boundary.digest(signature)})
    history.update(annotation_references=annotation_refs,annotation_ledgers=ledgers,
        heading_structure_rows=structures,heading_unannotated_ids=unannotated)
    return history


def exposure_payload(history,panels,ledger):
    old_texts={temporal.prior.normalized_source(s) for s in history['excluded_sources']}
    new_texts={temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows}
    require(not old_texts&new_texts,'new source overlaps prior inventory')
    old_rules={boundary.digest(c['rule']) for rows in history['pools'].values() for r in rows for c in r['clauses']}
    require(not old_rules&{boundary.digest(o['rule']) for a in ledger['document_rows'] for o in a['local_clause_coordinates']},
        'new local meaning overlaps old supported rules')
    lookup={a['candidate_id']:a for a in ledger['document_rows']}
    known={k:{r['role_masked_layout'] for r in v} for k,v in history['layout_rows'].items()}
    known['new_tuning']={role_layout(r,lookup[r['candidate_id']]) for r in panels['tuning']}
    structural={k:{r['heading_structure_sha256'] for r in v} for k,v in history['heading_structure_rows'].items()}
    structural['new_tuning']={boundary.digest(s) for r in panels['tuning'] for o in lookup[r['candidate_id']]['local_clause_coordinates'] for s in heading_structure(o)}
    evidence=[]
    for row in panels['fresh']:
        a=lookup[row['candidate_id']];layout=role_layout(row,a);matches=sorted(k for k,v in known.items() if layout in v)
        signatures=[s for o in a['local_clause_coordinates'] for s in heading_structure(o)]
        hashes=[boundary.digest(s) for s in signatures]
        structural_matches=sorted(k for k,v in structural.items() if any(h in v for h in hashes))
        require(not matches and not structural_matches,'fresh heading structure/layout already exposed; no novelty relabeling permitted')
        evidence.append({'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'case_group':a['case_group'],
            'role_masked_layout':layout,'matching_pools':matches,'layout_status':'unmatched_audited_combination',
            'heading_structures':signatures,'heading_structure_sha256':hashes,'structural_matching_pools':structural_matches})
    return {'schema':'legal-heading-boundary-exposure/v1','rows':evidence,
        'known_role_masked_layouts':{k:sorted(v) for k,v in known.items()},
        'known_heading_structure_sha256':{k:sorted(v) for k,v in structural.items()},
        'historical_layout_rows':history['layout_rows'],'historical_unannotated_unsupported_ids':history['unannotated_unsupported_ids'],
        'historical_heading_structure_rows':history['heading_structure_rows'],'historical_heading_unannotated_ids':history['heading_unannotated_ids'],
        'historical_document_references':history['document_references'],'historical_annotation_references':history['annotation_references'],
        'prior_condition_single_references':history['condition_single_references'],'prior_source_references':history['prior_source_references'],
        'historical_source_inventory_count':len(old_texts),'historical_source_inventory_sha256':boundary.digest(sorted(old_texts)),
        'real_exposed_views':history['real_exposed_views'],'new_source_overlap_count':0,'training_reused_without_new_examples':True,
        'claim':'Fresh punctuation/marker arrangements and heading/time order differ from current tuning and all directly annotated prior heading structures after masking heading words/numbers; full role layouts also unmatched. Historical unannotated headings/guards cannot support universal novelty claims. Authored profile only; no statutory gold.'}


def freeze(output,preservation_manifest_path=DEFAULT_PRESERVATION):
    output=Path(output).resolve();require(not output.exists(),'new output directory required')
    history=historical_inventory(preservation_manifest_path)
    panels,pairs,ledger,counts=make_panels();exposure=exposure_payload(history,panels,ledger)
    parent=history['prior_preservation_manifest']
    replay={k:read_ref(v) for k,v in parent['replay_references'].items()}
    heading=read_ref(parent['artifacts']['new_training_targets'])
    supervised_replay=[r for rows in replay.values() for r in rows if r['supported']]
    supervised_heading=[r for r in heading if r['supported']]
    require(len(supervised_replay)==528 and len(supervised_heading)==192,'same720 supported TRAIN required')
    roles=training_token_roles(supervised_replay+supervised_heading,
        {k:history['annotation_ledgers'][k] for k in ('prior_scope','prior_adapter')})
    output.mkdir(parents=True)
    artifacts={k:parent['artifacts'][k] for k in ('new_training_targets','training_pairs','training_sources')}
    artifacts['training_token_roles']=write_new(output/'training-token-roles.json',roles)
    for panel in COUNTS:
        suffix='.sealed.json' if panel=='fresh' else '.json'
        for kind,value in (('targets',panels[panel]),('pairs',pairs[panel])):
            key=panel+'_'+kind;artifacts[key]=write_new(output/(key.replace('_','-')+suffix),value)
        key=panel+'_sources';artifacts[key]=write_new(output/(key.replace('_','-')+'.json'),[source_row(r) for r in panels[panel]])
    artifacts['annotation_ledger']=write_new(output/'annotations.sealed.json',ledger)
    artifacts['exposure_audit']=write_new(output/'exposure-audit.sealed.json',exposure)
    manifest={'schema':SCHEMA,'generator':file_ref(__file__),'frozen_before_training':True,
        'dependencies':{k:file_ref(v.__file__) for k,v in (('preservation_corpus',preservation),('adapter_corpus',adapter),
            ('previous_scope',previous),('condition_corpus',condition),('temporal_corpus',temporal),('boundary_decoder',boundary))},
        'inputs':{'prior_preservation_corpus':history['prior_preservation_manifest_ref']},'artifacts':artifacts,
        'replay_references':parent['replay_references'],'retention_target_references':history['retention_target_references'],
        'training_annotation_references':{k:history['annotation_references'][k] for k in ('prior_scope','prior_adapter')},
        'counts':counts,'training_documents':1152,'supervised_training_documents':720,'excluded_unsupported_training_documents':432,
        'new_training_documents':0,'training_reused_without_changes':True,'training_token_role_counts':role_counts(roles),
        'source_order_seed':SHUFFLE_SEED,'sealed_artifacts':list(SEALED),'training_performed':False,
        'source_semantics_verified':False,'statutory_gold_available':False,
        'scope':'Matched supported-only token-boundary supervision; prior labels/scopes unchanged; new structurally distinct evaluation headings.'}
    return write_new(output/'manifest.json',manifest)


def load_training_inputs(manifest_path):
    """Admit only TRAIN token masks, tuning targets and new source-only holdout."""
    manifest=read_ref(file_ref(manifest_path))
    require(manifest['schema']==SCHEMA and manifest['frozen_before_training'] is True
        and manifest['sealed_artifacts']==list(SEALED),'frozen heading corpus/seals required')
    verify_ref(manifest['generator'])
    for pin in list(manifest['dependencies'].values())+list(manifest['inputs'].values()):verify_ref(pin)
    parent=read_ref(manifest['inputs']['prior_preservation_corpus'])
    require(parent['schema']==preservation.SCHEMA,'prior preservation corpus schema differs')
    require(manifest['training_documents']==1152 and manifest['supervised_training_documents']==720
        and manifest['excluded_unsupported_training_documents']==432 and manifest['new_training_documents']==0
        and manifest['training_reused_without_changes'] is True and manifest['source_order_seed']==SHUFFLE_SEED,
        'unchanged TRAIN/supported supervision denominator differs')
    expected_retention={**parent['retention_target_references'],'prior_preservation_tuning':parent['artifacts']['tuning_targets'],
        'prior_preservation_fresh':parent['artifacts']['fresh_targets']}
    require(manifest['replay_references']==parent['replay_references'] and manifest['retention_target_references']==expected_retention,
        'reused TRAIN or admitted retention references differ')
    a=manifest['artifacts']
    require(all(a[k]==parent['artifacts'][k] for k in ('new_training_targets','training_pairs','training_sources')),
        'prior training rows/pairs/source refs changed')
    require(set(manifest['counts'])==set(COUNTS) and all(manifest['counts'][p]['documents']==n
        and manifest['counts'][p]['supported']==manifest['counts'][p]['unsupported']==n//2 for p,n in COUNTS.items()),
        'evaluation counts differ')
    train=read_ref(a['new_training_targets']);pairs=read_ref(a['training_pairs']);adapter.validate_pairs(train,pairs,192)
    require(read_ref(a['training_sources'])==[source_row(r) for r in train],'unchanged training source order differs')
    replay={k:read_ref(v) for k,v in manifest['replay_references'].items()}
    require({k:len(v) for k,v in replay.items()}=={'original':192,'expanded':384,'prior_scope':192},'exact768 replay required')
    supported_replay=[r for rows in replay.values() for r in rows if r['supported']]
    supported_heading=[r for r in train if r['supported']]
    fit=supported_replay+supported_heading
    require(len(supported_replay)==528 and len(supported_heading)==192 and len({r['source_sha256'] for r in fit})==720,
        'all720 distinct supported TRAIN required')
    adapter_manifest=read_ref(parent['inputs']['prior_adapter_corpus']);scope_manifest=read_ref(adapter_manifest['inputs']['prior_scope_corpus'])
    annotation_refs={'prior_scope':scope_manifest['artifacts']['annotation_ledger'],'prior_adapter':adapter_manifest['artifacts']['annotation_ledger']}
    require(manifest['training_annotation_references']==annotation_refs,'TRAIN editorial annotation ancestry differs')
    roles=read_ref(a['training_token_roles'])
    require(roles==training_token_roles(fit,{k:read_ref(v) for k,v in annotation_refs.items()})
        and manifest['training_token_role_counts']==role_counts(roles),'TRAIN endpoint/editorial masks differ from direct source annotations')
    tune,tpairs=read_ref(a['tuning_targets']),read_ref(a['tuning_pairs']);validate_pairs(tune,tpairs,48)
    fresh=read_ref(a['fresh_sources']);legacy.validate_sources(fresh,192)
    require(read_ref(a['tuning_sources'])==[source_row(r) for r in tune],'tuning source/target order differs')
    for row in [source_row(r) for r in tune]+fresh:
        require(set(row)==SOURCE_KEYS and row['candidate_id']=='scope-'+sha(row['source_text'].encode())
            and row['source_sha256']==sha(row['source_text'].encode()),'closed opaque evaluation sources required')
        boundary.tokenize(row['source_text'])
    tuning={k:read_ref(v) for k,v in manifest['retention_target_references'].items()}
    require(len(tuning)==19 and 'heading_new' not in tuning,'complete19 historical panels required');tuning['heading_new']=tune
    require(sum(map(len,tuning.values()))==2160,'complete2160 admitted tuning documents required')
    for rows in list(replay.values())+list(tuning.values()):legacy.validate_references(rows,len(rows),sum(r['supported'] for r in rows))
    old=[r for rows in replay.values() for r in rows]+train
    new_hashes={r['source_sha256'] for r in tune+fresh}
    historical_hashes={r['source_sha256'] for rows in [old]+[v for k,v in tuning.items() if k!='heading_new'] for r in rows}
    require(len({r['source_sha256'] for r in old})==1152 and len(new_hashes)==288 and not new_hashes&historical_hashes,
        'unchanged TRAIN uniqueness or new source isolation differs')
    return {'manifest':manifest,'replay':replay,'new_train':train,'training_pairs':pairs,
        'boundary_training':fit,'supported_replay':supported_replay,'supported_heading':supported_heading,'training_token_roles':roles,
        'new_tuning':tune,'tuning_pairs':tpairs,'tuning':tuning,'fresh_sources':fresh}


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--prior-preservation-manifest',default=str(DEFAULT_PRESERVATION))
    args=parser.parse_args();print(json.dumps(freeze(args.output,args.prior_preservation_manifest),sort_keys=True))
