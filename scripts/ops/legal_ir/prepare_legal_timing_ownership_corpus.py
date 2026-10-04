#!/usr/bin/env python3
"""Append192 authored timing-ownership examples to frozen576 auxiliary rows.

The main4080 inventory is unchanged. Condition-owned timing is a whole opaque
applicability atom, not a nested temporal logic translation. Oracle document
inputs openly supply correct supported membership and occurrence intervals.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import random
import re
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import prepare_legal_role_span_rehearsal_corpus as previous
prior,temporal,construction=previous.prior,previous.temporal,previous.construction
require,sha,digest,file_ref,read_ref,verify_ref,write_new=(getattr(previous,k) for k in
    ('require','sha','digest','file_ref','read_ref','verify_ref','write_new'))
FIELDS,PAIR_KEYS,BLOCK_KEYS=previous.FIELDS,previous.PAIR_KEYS,previous.BLOCK_KEYS
SEALED,EVALUATION_ONLY=previous.SEALED,previous.EVALUATION_ONLY
SCHEMA='authored-legal-timing-ownership-corpus/v1'
COUNTS={'train':192,'tuning':192,'fresh':192,'document_tuning':96,'document_fresh':96}
FAMILIES=('front_to_actor_infix','front_to_modal_infix','actor_infix_to_trailing','modal_infix_to_front')
PREFIXES={'train':'Willowtiming','tuning':'Beechtiming','fresh':'Aspentiming','document_tuning':'Cedartiming','document_fresh':'Poplartiming'}
OWNERSHIP_CLASSES=('neither','condition_only','deadline_only','both')
CAPTIONS=previous.CAPTIONS
SHUFFLE_SEED=940731
DEFAULT_PRIOR=prior.ARTIFACTS/'legal-decoder-role-span-rehearsal-20261003/corpus-01/manifest.json'
DEFAULT_GENERATION=prior.ARTIFACTS/'legal-decoder-role-span-rehearsal-20261003/run-01/generation-frozen.json'
source_row,document_source=previous.source_row,previous.document_source


def presence_mask(row):return previous.presence_mask(row)


def validate_row(row):
    require(row['id'].startswith(('timing-','oracle-')),'opaque timing/occurrence identity required')
    if row['id'].startswith('timing-'):require(row['id']=='timing-'+sha(row['source_text'].encode()),'timing source identity differs')
    temporal.validate_row({**row,'id':'temporal-presence-validation-'+sha(row['source_text'].encode())[:24]})
    return row


def placement(family,side):
    C,E,T='conditions','exceptions','temporal'
    return {
        FAMILIES[0]:(((C,T),(E,),(),()),((T,),(C,),(),(E,))),
        FAMILIES[1]:(((E,C,T),(),(),()),((),(E,),(C,T),())),
        FAMILIES[2]:(((),(C,T),(E,),()),((),(),(),(E,T,C))),
        FAMILIES[3]:(((),(E,),(T,C),()),((T,C,E),(),(),()))}[family][side]


def render(panel,case,family,modality,mask,caption,side):
    require(panel in PREFIXES and type(case) is int and case>=0 and family in FAMILIES and modality in 'OPF'
            and type(mask) is int and mask in range(8) and type(caption) is int and caption in range(3)
            and type(side) is int and side in (0,1),'known bounded timing factors required')
    name=PREFIXES[panel]+f'{case:04d}';fi=FAMILIES.index(family)
    kind=('days','hours','calendar')[(case//8+fi)%3]
    condition_time={'days':f'within {11+case%13} days of publication','hours':f'within {25+case%17} hours of publication',
                    'calendar':f'before {2091+list(PREFIXES).index(panel)}-03-{1+case%28:02d}'}[kind]
    deadline={'days':f'within {61+case%19} days','hours':f'within {91+case%23} hours',
              'calendar':f'before {2096+list(PREFIXES).index(panel)}-09-{1+case%28:02d}'}[kind]
    rule={'modality':modality,'actor':f'the {name} '+('Registry','Dept. of Records','Filing Duty Office','Record Duty Authority')[case%4],
          'action':temporal.VERBS[(case+fi)%len(temporal.VERBS)],'object':f'the {name.lower()} filing packet',
          'conditions':[f'the {name.lower()} application was received {condition_time}'] if mask&1 else [],
          'exceptions':[f'the {name.lower()} exemption is active'] if mask&2 else [],
          'temporal':[deadline] if mask&4 else []}
    w=prior.CoordinateWriter();notes=[];cues=[];timing_spans=[]
    def facet(field):
        value=rule[field];value=value[0] if isinstance(value,list) else value
        start=len(w.text);w.add(value,field)
        if field=='conditions':
            offset=len(value)-len(condition_time)
            timing_spans.append({'owner':'conditions','char_start':start+offset,'char_end':len(w.text),
                'source_text':condition_time,'relation':'opaque_receipt_timing_applicability_atom'})
        elif field=='temporal':
            timing_spans.append({'owner':'temporal','char_start':start,'char_end':len(w.text),
                'source_text':deadline,'relation':'independent_action_deadline'})
    def qualifier(field):
        cue=temporal.CONDITION_CUES[(case+side+fi)%3] if field=='conditions' else temporal.EXCEPTION_CUES[(case+side)%3] if field=='exceptions' else ''
        if panel.startswith('document_') and cue=='provided that':cue='when'
        if cue:
            start=len(w.text);w.add(cue+' ');cues.append({'field':field,'start_char':start,'end_char':len(w.text),'source_text':cue+' '})
        facet(field)
    def note():
        start=len(w.text);text=CAPTIONS[caption];w.add(text)
        notes.append({'start_char':start,'end_char':len(w.text),'source_text':text,'author_stipulated_role':'nonoperative_editorial_context'})
    front,actor_infix,modal_infix,suffix=placement(family,side)
    headed=not(fi==0 and side==0)
    if headed and side==0:note()
    for field in front:
        if rule[field]:qualifier(field);w.add(', ')
    if headed and side==1:note()
    facet('actor')
    for field in actor_infix:
        if rule[field]:w.add(', ');qualifier(field);w.add(',')
    w.add(' ');w.add(temporal.TRIGGERS[modality][side],'trigger')
    for field in modal_infix:
        if rule[field]:w.add(', ');qualifier(field);w.add(',')
    w.add(' ');facet('action');w.add(' ');facet('object')
    for field in suffix:
        if rule[field]:w.add(' ');qualifier(field)
    w.add('.')
    row=validate_row({'id':'timing-'+sha(w.text.encode()),'source_text':w.text,'canonical_ir':{'rules':[rule]},
        'facet_spans':{f:w.spans.get(f) for f in FIELDS},'trigger_span':w.spans['trigger'],'domain':'new','trigger_supervised':True})
    ownership='both' if mask&1 and mask&4 else 'condition_only' if mask&1 else 'deadline_only' if mask&4 else 'neither'
    layout=temporal.role_layout(row)
    annotation={'id':row['id'],'source_sha256':sha(w.text.encode()),'panel':panel,'family':family,'side':side,
        'case_group':'case-'+sha(f'timing-ownership/{panel}/{case}'.encode()),'caption_style':caption,'presence_mask':mask,
        'facet_spans':deepcopy(row['facet_spans']),'trigger_span':list(row['trigger_span']),'editorial_context':notes,'qualifier_cues':cues,
        'timing_ownership':ownership,'timing_role_spans':sorted(timing_spans,key=lambda s:s['char_start']),
        'condition_owned_temporal_language':bool(mask&1),'temporal_kind':kind if mask&4 else None,
        'role_masked_layout':layout,'layout_sha256':sha(layout.encode()),'annotation_authority':previous.AUTHORITY}
    validate_timing_annotation(row,annotation)
    return row,annotation


def validate_timing_annotation(row,annotation):
    validate_row(row);rule=row['canonical_ir']['rules'][0];source=row['source_text'];a=annotation
    expected='both' if rule['conditions'] and rule['temporal'] else 'condition_only' if rule['conditions'] else 'deadline_only' if rule['temporal'] else 'neither'
    require(a['timing_ownership']==expected and a['condition_owned_temporal_language'] is bool(rule['conditions'])
            and a['facet_spans']==row['facet_spans'] and a['trigger_span']==row['trigger_span'] and a['source_sha256']==sha(source.encode()),'timing ownership source binding differs')
    expected_spans=[]
    if rule['conditions']:
        atom=rule['conditions'][0];marker=' application was received ';require(marker in atom,'complete receipt predicate required')
        suffix=atom.split(marker,1)[1];start=row['facet_spans']['conditions'][1]-len(suffix)
        require(re.fullmatch(r'within \d+ (?:days|hours) of publication|before \d{4}-\d{2}-\d{2}',suffix),'explicit condition timing origin/date required')
        expected_spans.append({'owner':'conditions','char_start':start,'char_end':row['facet_spans']['conditions'][1],
            'source_text':suffix,'relation':'opaque_receipt_timing_applicability_atom'})
    if rule['temporal']:
        span=row['facet_spans']['temporal'];expected_spans.append({'owner':'temporal','char_start':span[0],'char_end':span[1],
            'source_text':rule['temporal'][0],'relation':'independent_action_deadline'})
    require(a['timing_role_spans']==sorted(expected_spans,key=lambda s:s['char_start']),'timing lexical interval escaped canonical owning facet')
    for value in expected_spans:
        span=row['facet_spans'][value['owner']]
        require(span[0]<=value['char_start']<value['char_end']<=span[1]
                and source[value['char_start']:value['char_end']]==value['source_text'],'timing subspan source mismatch')
    if rule['conditions'] and rule['temporal']:
        require(rule['temporal'][0] not in rule['conditions'][0],'both-owned examples must avoid ambiguous identical literal')
    return row


def validate_document_timing(rows,annotations):
    lookup={r['candidate_id']:r for r in rows}
    require(len(lookup)==len(rows)==len(annotations),'complete document timing annotations required')
    for annotation in annotations:
        row=lookup[annotation['candidate_id']]
        for index,coordinate in enumerate(annotation['local_clause_coordinates']):
            start,end=coordinate['char_start'],coordinate['char_end'];text=row['source_text'][start:end]+'.'
            local={'id':'oracle-'+digest([row['candidate_id'],index]),'source_text':text,
                'canonical_ir':{'rules':[coordinate['rule']]},
                'facet_spans':{f:[v-start for v in span] if span else None for f,span in coordinate['facet_spans'].items()},
                'trigger_span':[v-start for v in coordinate['trigger_span']],'domain':'new','trigger_supervised':True}
            label={**coordinate,'source_sha256':sha(text.encode()),'facet_spans':local['facet_spans'],'trigger_span':local['trigger_span'],
                'timing_role_spans':[{**s,'char_start':s['char_start']-start,'char_end':s['char_end']-start} for s in coordinate['timing_role_spans']]}
            validate_timing_annotation(local,label)


def make_panel(panel):
    require(panel in ('train','tuning','fresh'),'single panel required');rows=[];annotations=[];pairs=[]
    for case,(family,modal,mask) in enumerate(product(FAMILIES,'OPF',range(8))):
        caption=('OPF'.index(modal)+FAMILIES.index(family))%3
        pair=[render(panel,case,family,modal,mask,caption,side) for side in (0,1)]
        rows.extend(v[0] for v in pair);annotations.extend(v[1] for v in pair);left,right=(v[0] for v in pair);group=pair[0][1]['case_group']
        pairs.append({'pair_id':group,'case_group':group,'left_id':left['id'],'right_id':right['id'],'canonical_ir_sha256':digest(left['canonical_ir'])})
    previous.validate_pairs(rows,pairs,96);random.Random(SHUFFLE_SEED+list(PREFIXES).index(panel)).shuffle(rows)
    return rows,annotations,pairs


def make_blocks(rows,pairs,annotations):
    labels={a['id']:a for a in annotations};lookup={r['id']:r for r in rows};mapping={}
    for pair in pairs:
        a=labels[pair['left_id']];modal=lookup[pair['left_id']]['canonical_ir']['rules'][0]['modality']
        mapping[(a['family'],modal,a['presence_mask'])]=pair['pair_id']
    blocks=[]
    for family,modal,mask in product(FAMILIES,'OPF',range(4)):
        ids=[mapping[(family,modal,m)] for m in (mask,7-mask)]
        blocks.append({'block_id':'block-'+digest(ids),'pair_ids':ids})
    validate_blocks(rows,pairs,blocks,48)
    return blocks


def validate_blocks(rows,pairs,blocks,expected):
    require(type(blocks) is list and len(blocks)==expected and len(rows)==expected*4 and len(pairs)==expected*2,'complete complement block counts differ')
    by_id={r['id']:r for r in rows};pm={p['pair_id']:p for p in pairs};used=set()
    require(len({b['block_id'] for b in blocks})==expected,'duplicate block identity')
    for b in blocks:
        require(set(b)==BLOCK_KEYS and type(b['pair_ids']) is list and len(b['pair_ids'])==len(set(b['pair_ids']))==2
                and set(b['pair_ids'])<=set(pm) and not used.intersection(b['pair_ids']) and b['block_id']=='block-'+digest(b['pair_ids']),'closed unique two-pair block required')
        selected=[by_id[pm[p][side]] for p in b['pair_ids'] for side in ('left_id','right_id')]
        require(len({r['id'] for r in selected})==4 and presence_mask(selected[0])^presence_mask(selected[2])==7
                and all(sum(bool(r['canonical_ir']['rules'][0][f]) for r in selected)==2 for f in FIELDS[3:]),'C/E/T block must have2present2absent')
        require(len({r['canonical_ir']['rules'][0]['modality'] for r in selected})==1,'shared block modality required')
        used.update(b['pair_ids'])
    require(used==set(pm),'unpaired auxiliary rows')


def make_documents(panel):
    require(panel in ('document_tuning','document_fresh'),'document panel required');rows=[];annotations=[];pairs=[]
    for case in range(48):
        count=2+case%2
        local=[render(panel,case*3+i,FAMILIES[(case+i)%4],'OPF'[(case+i)%3],(case+i*3)%8,(case+i)%3,(case//4+i)%2) for i in range(count)]
        if case%8==0:local[-1]=deepcopy(local[0])
        ids=[]
        for supported in (True,False):
            text='';clauses=[];coordinates=[];attachment=None
            for index,(row,label) in enumerate(local):
                if index:
                    gap=(' unless ',' except when ',' except where ')[case%3] if not supported and index==1 else '\n' if case%2 else ' '
                    start=len(text);text+=gap
                    if not supported and index==1:attachment={'start_char':start,'end_char':len(text),'source_text':gap,'parent_occurrence':0,'child_occurrence':1,'declared_relation':'nested_normative_exception_outside_flat_profile'}
                start=len(text);body=row['source_text'][:-1];text+=body
                coordinate={'occurrence_index':index,'char_start':start,'char_end':len(text),'rule':deepcopy(row['canonical_ir']['rules'][0]),
                    'facet_spans':{f:[v+start for v in span] if span else None for f,span in row['facet_spans'].items()},
                    'trigger_span':[v+start for v in row['trigger_span']],
                    'editorial_context':[{**n,'start_char':n['start_char']+start,'end_char':n['end_char']+start} for n in label['editorial_context']],
                    'family':label['family'],'presence_mask':label['presence_mask'],'caption_style':label['caption_style'],
                    'timing_ownership':label['timing_ownership'],'timing_role_spans':[{**s,'char_start':s['char_start']+start,'char_end':s['char_end']+start} for s in label['timing_role_spans']],
                    'condition_owned_temporal_language':label['condition_owned_temporal_language'],'temporal_kind':label['temporal_kind']}
                coordinates.append(coordinate)
                if supported or index!=0:text+='.'
                if supported:clauses.append({'char_start':start,'char_end':len(text),'rule':deepcopy(coordinate['rule'])})
            h=sha(text.encode());identity='document-'+h;ids.append(identity)
            row={'candidate_id':identity,'source_text':text,'source_sha256':h,'supported':supported,
                'construction':'timing_ownership_independent' if supported else 'unsupported/nested_normative_exception',
                'repeated_rule_occurrences':supported and len({digest(v['rule']) for v in clauses})<len(clauses),
                'clauses':clauses,'unsupported_reason':None if supported else 'nested_normative_exception','label_origin':previous.AUTHORITY}
            construction.validate_document(row);rows.append(row)
            annotations.append({'candidate_id':identity,'source_sha256':h,'panel':panel,'case_group':'case-'+sha(f'timing-ownership/{panel}/{case}'.encode()),
                'supported':supported,'local_clause_coordinates':coordinates,'scope_attachment':attachment,'annotation_authority':previous.AUTHORITY})
        pairs.append({'pair_id':'pair-'+sha(f'timing-ownership/{panel}/{case}'.encode()),'case_group':annotations[-1]['case_group'],
            'independent_id':ids[0],'nested_id':ids[1],'local_clause_body_sha256':[sha(v[0]['source_text'][:-1].encode()) for v in local]})
    random.Random(SHUFFLE_SEED+list(PREFIXES).index(panel)).shuffle(rows)
    previous.validate_document_pairs(rows,pairs,annotations)
    return rows,annotations,pairs


def make_panels():
    panels={};pairs={};ledger={'schema':'legal-timing-ownership-annotations/v1','single_rows':[],'document_rows':[]}
    for panel in ('train','tuning','fresh'):
        panels[panel],labels,pairs[panel]=make_panel(panel);ledger['single_rows'].extend(labels)
    for panel in ('document_tuning','document_fresh'):
        panels[panel],labels,pairs[panel]=make_documents(panel);ledger['document_rows'].extend(labels)
    blocks=make_blocks(panels['train'],pairs['train'],[a for a in ledger['single_rows'] if a['panel']=='train'])
    validate_panels(panels,pairs,blocks,ledger)
    return panels,pairs,blocks,ledger


def validate_panels(panels,pairs,blocks,ledger):
    require({k:len(v) for k,v in panels.items()}==COUNTS,'new timing panel counts differ')
    labels={a['id']:a for a in ledger['single_rows']};sources=set();meanings=set();cases=set()
    for panel in ('train','tuning','fresh'):
        rows=panels[panel];previous.validate_pairs(rows,pairs[panel],96)
        require(Counter((r['canonical_ir']['rules'][0]['modality'],presence_mask(r)) for r in rows)=={(m,k):8 for m in 'OPF' for k in range(8)},'all8masks crossed modalities required')
        require(Counter(labels[r['id']]['timing_ownership'] for r in rows)=={k:48 for k in OWNERSHIP_CLASSES},'four timing ownership classes must balance')
        require(Counter(labels[r['id']]['caption_style'] for r in rows)=={k:64 for k in range(3)},'caption styles must balance')
        for r in rows:validate_timing_annotation(r,labels[r['id']])
        ss={prior.normalized_source(r['source_text']) for r in rows};mm={digest(r['canonical_ir']) for r in rows};cc={p['case_group'] for p in pairs[panel]}
        require(len(ss)==192 and len(mm)==len(cc)==96 and not (ss&sources or mm&meanings or cc&cases),'single split source/meaning/case collision')
        sources|=ss;meanings|=mm;cases|=cc
    validate_blocks(panels['train'],pairs['train'],blocks,48)
    for panel in ('document_tuning','document_fresh'):
        rows=panels[panel];annotations=[a for a in ledger['document_rows'] if a['panel']==panel]
        previous.validate_document_pairs(rows,pairs[panel],annotations);validate_document_timing(rows,annotations)
        pack=previous.oracle_pack(rows,annotations)
        require(len(pack['targets'])==120 and len(pack['document_sources'])==48,'oracle supports48docs120occurrences')
        ss={prior.normalized_source(r['source_text']) for r in rows+pack['targets']};mm={digest(r['canonical_ir']) for r in pack['targets']};cc={a['case_group'] for a in annotations}
        require(not(ss&sources or mm&meanings or cc&cases),'document versus single/split collision')
        sources|=ss;meanings|=mm;cases|=cc
    return {'case_groups':384,'cross_split_source_overlap':0,'cross_split_meaning_overlap':0,'cross_split_case_overlap':0,
            'grammar_and_templates_shared':True,'structural_novelty_claimed':False}


def historical_inputs(prior_path,generation_path):
    old=previous.load_training_inputs(prior_path);m=old['manifest'];generation=read_ref(file_ref(generation_path))
    config=read_ref(generation['config'])
    require(config['corpus_manifest']==file_ref(prior_path) and generation['all_training_selection_and_generation_complete'] is True,'complete prior role generation/corpus binding required')
    a=m['artifacts'];fresh=read_ref(a['fresh_targets']);docs=read_ref(a['fresh_document_targets']);ledger=read_ref(a['annotation_ledger'])
    pack=previous.oracle_pack(docs,[v for v in ledger['document_rows'] if v['panel']=='document_fresh'])
    require(pack['targets']==read_ref(a['fresh_oracle_targets']),'prior released fresh oracle target binding differs')
    return old,generation,{'tuning':old['new_tuning'],'fresh':fresh},{'role_tuning':old['document_tuning'],'role_fresh':docs},pack,ledger


def known_inventory(old,role_targets,role_documents,role_pack):
    legacy,atom_manifest,condition_targets,old_docs,old_packs=previous.historical_inputs(old['manifest']['inputs']['legacy_config']['path'],old['manifest']['inputs']['prior_atom_corpus']['path'])
    pools,excluded,refs,source_refs,real=previous.exposure_inventory(legacy,atom_manifest,condition_targets,old_docs,old_packs)
    pools.update(prior_role_train=old['aux_rows'],prior_role_tuning=role_targets['tuning'],prior_role_fresh=role_targets['fresh'],
        prior_role_document_tuning=old['oracle_targets']['new'],prior_role_document_fresh=role_pack['targets'])
    for rows in role_documents.values():excluded.update(r['source_text'] for r in rows)
    for rows in pools.values():excluded.update(r['source_text'] for r in rows)
    return pools,excluded,refs,source_refs,real


def freeze(output,prior_path=DEFAULT_PRIOR,generation_path=DEFAULT_GENERATION):
    output=Path(output).resolve();require(not output.exists(),'new output directory required')
    old,generation,role_targets,role_docs,role_pack,old_ledger=historical_inputs(prior_path,generation_path)
    panels,pairs,blocks,ledger=make_panels();split=validate_panels(panels,pairs,blocks,ledger)
    packs={p:previous.oracle_pack(panels[p],[a for a in ledger['document_rows'] if a['panel']==p]) for p in ('document_tuning','document_fresh')}
    known,excluded,refs,source_refs,real=known_inventory(old,role_targets,role_docs,role_pack)
    normalized={prior.normalized_source(s) for s in excluded};checked=[r['source_text'] for rows in panels.values() for r in rows]+[r['source_text'] for pack in packs.values() for r in pack['targets']]
    require(not {prior.normalized_source(s) for s in checked}&normalized,'new ownership source repeats old train/evaluated text')
    combined=old['aux_rows']+panels['train'];combined_pairs=old['aux_pairs']+pairs['train'];combined_blocks=old['aux_blocks']+blocks
    previous.validate_pairs(combined,combined_pairs,384);validate_blocks(combined,combined_pairs,combined_blocks,192)
    output.mkdir(parents=True,exist_ok=False);artifacts={}
    def save(key,value):artifacts[key]=write_new(output/(key.replace('_','-')+('.sealed.json' if key in SEALED else '.json')),value)
    for key,value in {'aux_rows':combined,'aux_pairs':combined_pairs,'aux_blocks':combined_blocks,
        'ownership_rows':panels['train'],'ownership_pairs':pairs['train'],'ownership_blocks':blocks,
        'new_tuning':panels['tuning'],'tuning_pairs':pairs['tuning'],'fresh_targets':panels['fresh'],'fresh_pairs':pairs['fresh'],
        'document_tuning':panels['document_tuning'],'document_tuning_pairs':pairs['document_tuning'],
        'fresh_document_targets':panels['document_fresh'],'fresh_document_pairs':pairs['document_fresh'],
        'fresh_sources':[source_row(r) for r in panels['fresh']],
        'document_tuning_sources':[document_source(r) for r in panels['document_tuning']],
        'fresh_document_sources':[document_source(r) for r in panels['document_fresh']],
        'ownership_training_annotation_ledger':{'schema':ledger['schema'],'single_rows':[a for a in ledger['single_rows'] if a['panel']=='train'],'document_rows':[]},
        'training_annotation_ledger':{'schema':'combined-role-and-timing-auxiliary-annotations/v1',
            'single_rows':old['training_annotation_ledger']['single_rows']+[a for a in ledger['single_rows'] if a['panel']=='train'],'document_rows':[]},
        'tuning_annotation_ledger':{'schema':ledger['schema'],'single_rows':[a for a in ledger['single_rows'] if a['panel']=='tuning'],
            'document_rows':[a for a in ledger['document_rows'] if a['panel']=='document_tuning']},'annotation_ledger':ledger}.items():save(key,value)
    admitted={kind:{**{p:v for p,v in old['oracle_'+kind].items() if p!='new'},'role_tuning':old['oracle_'+kind]['new'],
        'role_fresh':role_pack[kind],'new':packs['document_tuning'][kind]} for kind in ('sources','targets','occurrences','boundaries','document_sources')}
    for kind,value in admitted.items():save('oracle_'+kind,value);save('fresh_oracle_'+kind,packs['document_fresh'][kind])
    known.update(new_ownership_train=panels['train'],new_ownership_tuning=panels['tuning'],new_ownership_document_tuning=packs['document_tuning']['targets'])
    layouts={p:{temporal.role_layout(r) for r in rows} for p,rows in known.items()};evidence=[]
    for panel,rows in (('single',panels['fresh']),('oracle_document',packs['document_fresh']['targets'])):
        for row in rows:
            layout=temporal.role_layout(row);matches=sorted(p for p,values in layouts.items() if layout in values)
            evidence.append({'id':row['id'],'panel':panel,'source_sha256':sha(row['source_text'].encode()),'role_masked_layout':layout,
                'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination',
                'matched_new_ownership_training':'new_ownership_train' in matches})
    save('exposure_audit',{'schema':'legal-timing-ownership-exposure/v1','rows':evidence,'known_pool_counts':{k:len(v) for k,v in known.items()},
        'known_role_masked_layouts':{k:sorted(v) for k,v in layouts.items()},'historical_document_references':refs,'historical_source_references':source_refs,
        'prior_source_hashes_sha256':digest(sorted(sha(s.encode()) for s in normalized)),'real_exposed_views':real,'new_source_overlap':0,
        'split_audit':split,'structural_novelty_claimed':False,'claim':'Held-out entities/cases/meanings, deliberately reused shared grammar and structural templates.'})
    plan=write_new(output/'plan.json',{'schema':SCHEMA,'counts':COUNTS,'main_training_rows':4080,'retained_auxiliary_rows':576,'new_auxiliary_rows':192,'combined_auxiliary_rows':768,
        'combined_pairs':384,'combined_complement_blocks':192,'timing_ownership_classes':list(OWNERSHIP_CLASSES),'single_rows_per_ownership_class':48,
        'condition_timing_policy':'Complete receipt-timing applicability atom; not an action deadline or nested temporal logic validation.',
        'both_policy':'Distinct exact timing literals bind unambiguously to condition and action deadline.',
        'provided_that_policy':'Single clauses only; replaced by when in documents.',
        'oracle_policy':'Supported documents only;120occurrences in48docs, supplied boundaries and supported membership.',
        'all_previous_role_tuning_and_fresh_are_admitted_retention':True,'structural_novelty_claimed':False,'statutory_gold':False})
    manifest={'schema':SCHEMA,'frozen_before_training':True,'generator':file_ref(__file__),
        'dependencies':{k:file_ref(v.__file__) for k,v in (('previous_role',previous),('temporal',temporal),('coordinates',prior),('construction',construction))},
        'inputs':{'prior_role_corpus':file_ref(prior_path),'prior_role_generation':file_ref(generation_path)},
        'artifacts':artifacts,'plan':plan,'counts':COUNTS,'main_training_rows':4080,'main_training_sha256':digest(old['legacy']['training']),
        'retained_auxiliary_refs':{k:old['manifest']['artifacts'][k] for k in ('aux_rows','aux_pairs','aux_blocks')},
        'retained_auxiliary_rows':576,'new_auxiliary_rows':192,'combined_auxiliary_rows':768,
        'sealed_artifacts':list(SEALED),'evaluation_only_artifacts':list(EVALUATION_ONLY),'split_audit':split,
        'oracle_admitted_occurrences':{p:len(v) for p,v in admitted['targets'].items()},'fresh_oracle_occurrences':120,
        'training_performed':False,'source_semantics_verified':False,'training_qualified_as_statutory_gold':False}
    return write_new(output/'manifest.json',manifest)


def _manifest(path):
    m=read_ref(file_ref(path));require(m['schema']==SCHEMA and m['frozen_before_training'] is True and m['counts']==COUNTS
        and m['sealed_artifacts']==list(SEALED) and m['evaluation_only_artifacts']==list(EVALUATION_ONLY),'frozen timing corpus required')
    verify_ref(m['generator'])
    for pin in list(m['dependencies'].values())+list(m['inputs'].values()):verify_ref(pin)
    return m


def load_training_inputs(manifest_path):
    m=_manifest(manifest_path);a=m['artifacts']
    old,generation,role_targets,role_docs,role_pack,oldledger=historical_inputs(m['inputs']['prior_role_corpus']['path'],m['inputs']['prior_role_generation']['path'])
    require(m['retained_auxiliary_refs']=={k:old['manifest']['artifacts'][k] for k in ('aux_rows','aux_pairs','aux_blocks')}
            and digest(old['legacy']['training'])==m['main_training_sha256'],'exact prior auxiliary/main binding differs')
    new=read_ref(a['ownership_rows']);pairs=read_ref(a['ownership_pairs']);blocks=read_ref(a['ownership_blocks'])
    train=read_ref(a['aux_rows']);allpairs=read_ref(a['aux_pairs']);allblocks=read_ref(a['aux_blocks'])
    require(train==old['aux_rows']+new and allpairs==old['aux_pairs']+pairs and allblocks==old['aux_blocks']+blocks,'old576auxiliary prefix changed')
    previous.validate_pairs(new,pairs,96);previous.validate_pairs(train,allpairs,384);validate_blocks(new,pairs,blocks,48);validate_blocks(train,allpairs,allblocks,192)
    trainlabels=read_ref(a['ownership_training_annotation_ledger']);lookup={v['id']:v for v in trainlabels['single_rows']}
    require(len(lookup)==len(new)==192,'new timing TRAIN annotations omitted/duplicated')
    for row in new:validate_timing_annotation(row,lookup[row['id']])
    combinedlabels=read_ref(a['training_annotation_ledger']);require(combinedlabels['single_rows']==old['training_annotation_ledger']['single_rows']+trainlabels['single_rows'],'TRAIN annotation prefix changed')
    tune=read_ref(a['new_tuning']);tpairs=read_ref(a['tuning_pairs']);previous.validate_pairs(tune,tpairs,96)
    tledger=read_ref(a['tuning_annotation_ledger']);labels={r['id']:r for r in tledger['single_rows']}
    for row in tune:validate_timing_annotation(row,labels[row['id']])
    docs=read_ref(a['document_tuning']);dpairs=read_ref(a['document_tuning_pairs']);previous.validate_document_pairs(docs,dpairs,tledger['document_rows'])
    validate_document_timing(docs,tledger['document_rows'])
    require([document_source(r) for r in docs]==read_ref(a['document_tuning_sources']),'document tuning source order differs')
    fresh=read_ref(a['fresh_sources']);freshdocs=read_ref(a['fresh_document_sources'])
    require(len(fresh)==192 and len(freshdocs)==96 and all(set(r)=={'id','source_text'} and r['id']=='timing-'+sha(r['source_text'].encode()) for r in fresh),'fresh single source schema differs')
    require(all(set(r)==construction.SOURCE_KEYS and r['source_sha256']==sha(r['source_text'].encode()) and r['candidate_id']=='document-'+r['source_sha256'] for r in freshdocs),'fresh document source schema differs')
    pack=previous.oracle_pack(docs,tledger['document_rows']);oracle={k:read_ref(a['oracle_'+k]) for k in ('sources','targets','occurrences','boundaries','document_sources')}
    for kind,value in oracle.items():
        expected={**{p:v for p,v in old['oracle_'+kind].items() if p!='new'},'role_tuning':old['oracle_'+kind]['new'],'role_fresh':role_pack[kind],'new':pack[kind]}
        require(value==expected,'admitted oracle source/target/occurrence ancestry differs')
    tuningpanels={**{'legacy_'+k:v for k,v in old['legacy']['tuning'].items()},**{'retention_'+k:v for k,v in old['legacy']['retention_targets'].items()},
        'prior_condition':old['prior_condition_targets'],'role_tuning':role_targets['tuning'],'role_fresh':role_targets['fresh'],'new':tune,
        **{'oracle_'+p:v for p,v in oracle['targets'].items()}}
    runtime_tuning,provenance=previous.deduplicate_runtime_tuning(tuningpanels)
    main={r['source_text'] for r in old['legacy']['training']};fit={r['source_text'] for r in train};evaluated={r['source_text'] for r in runtime_tuning}
    require(len(main)==4080 and len(fit)==768 and not main&fit and not(main|fit)&evaluated,'main/auxiliary/evaluation source overlap')
    newtexts=[r['source_text'] for r in fresh+freshdocs];require(len(set(newtexts))==288 and not set(newtexts)&(main|fit|evaluated),'fresh sources overlap admitted inputs')
    return {**old,'manifest':m,'prior_role_inputs':old,'prior_role_generation':generation,'role_retention_targets':role_targets,
        'role_documents':{'tuning':role_docs['role_tuning'],'fresh':role_docs['role_fresh']},'aux_rows':train,'aux_pairs':allpairs,'aux_blocks':allblocks,
        'ownership_rows':new,'ownership_pairs':pairs,'ownership_blocks':blocks,'new_tuning':tune,'tuning_pairs':tpairs,
        'document_tuning':docs,'document_tuning_pairs':dpairs,'fresh_sources':fresh,'fresh_document_sources':freshdocs,
        **{'oracle_'+k:v for k,v in oracle.items()},'runtime_tuning':runtime_tuning,'runtime_tuning_provenance':provenance,
        'training_annotation_ledger':combinedlabels,'ownership_training_annotation_ledger':trainlabels,'tuning_annotation_ledger':tledger}


def load_evaluation_sources(manifest_path):
    m=_manifest(manifest_path);a=m['artifacts'];sources=read_ref(a['fresh_sources']);docs=read_ref(a['fresh_document_sources'])
    pack={k:read_ref(a['fresh_oracle_'+k]) for k in ('sources','occurrences','boundaries','document_sources')}
    require(len(sources)==192 and len(docs)==96 and len(pack['sources'])==120 and len(pack['document_sources'])==48
            and all(r in docs for r in pack['document_sources']),'fresh oracle/source denominators differ')
    previous.validate_oracle_pack(pack['document_sources'],pack['sources'],pack['occurrences'],pack['boundaries'])
    return {'fresh_sources':sources,'fresh_document_sources':docs,**{'oracle_'+k:v for k,v in pack.items()},
            'assistance':'Oracle supplied boundaries and supported eligibility, not inferred segmentation.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--prior-role-manifest',default=str(DEFAULT_PRIOR));parser.add_argument('--prior-role-generation',default=str(DEFAULT_GENERATION))
    args=parser.parse_args();print(json.dumps(freeze(args.output,args.prior_role_manifest,args.prior_role_generation),sort_keys=True))
