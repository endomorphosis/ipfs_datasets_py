#!/usr/bin/env python3
"""Author source-bound atom/end contrasts; previous frozen corpora stay immutable.

All labels describe an authored flat profile, not statute meaning. Current fresh
references and derived evidence remain sealed until independent qualification.
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
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import prepare_legal_heading_boundary_corpus as heading
previous,temporal,boundary,legacy=heading.previous,heading.temporal,heading.boundary,heading.legacy
require,sha,file_ref,read_ref,verify_ref,write_new=(getattr(previous,k) for k in ('require','sha','file_ref','read_ref','verify_ref','write_new'))
FIELDS,SOURCE_KEYS,ROW_KEYS,SEALED=heading.FIELDS,heading.SOURCE_KEYS,heading.ROW_KEYS,heading.SEALED
SCHEMA='authored-legal-atom-boundary-corpus/v1'
COUNTS={'train':144,'tuning':96,'fresh':192}
PREFIXES={'train':'Lindenatom','tuning':'Hazelatom','fresh':'Cypressatom'}
TIME_KINDS=('none','days','hours','calendar')
FRONT_CLASSES=('C','E','CE')
HEADINGS=('(2) Filing duty: ','Record duty [2]. ')
ATOM_FIELDS=('actor','temporal','exceptions')
ATOM_ROLE_KEYS={'candidate_id','source_sha256','inter_clause_end_token_indices','atom_interior_negative_token_indices','atom_spans','provenance'}
ATOM_PROVENANCE='pinned_supported_train_atoms_and_inter_clause_endpoints/v1'
TRAIN_PAIR_KEYS={'pair_id','forward_id','rotated_id','local_clause_body_sha256'}
FACTOR_KEYS={'front_class','preceding_time_kind','first_modality','clause_count','variant','child_structure'}
STRUCTURES={'train':'time_heading_qualifiers_actor','tuning':'heading_time_qualifiers_actor','fresh':'qualifiers_time_heading_actor'}
SHUFFLE_SEED=924173
DEFAULT_HEADING=temporal.prior.ARTIFACTS/'legal-decoder-heading-boundary-20261003/corpus-01/manifest.json'
source_row=heading.source_row


def factor_schedule(panel):
    require(panel in COUNTS,'known atom panel required')
    result=[]
    if panel=='train':
        for front,time,modal,count in product(FRONT_CLASSES,TIME_KINDS,'OPF',(2,3)):
            result.append({'front_class':front,'preceding_time_kind':time,'first_modality':modal,
                'clause_count':count,'variant':len(result)%4,'child_structure':STRUCTURES[panel]})
    else:
        for front,time,count,variant in product(FRONT_CLASSES,TIME_KINDS,(2,3),range(2 if panel=='tuning' else 4)):
            result.append({'front_class':front,'preceding_time_kind':time,'first_modality':'OPF'[len(result)%3],
                'clause_count':count,'variant':variant,'child_structure':STRUCTURES[panel]})
    require(len(result)*2==COUNTS[panel],'exact atom factor schedule required')
    return result


def render_local(panel,case,ordinal,factors):
    require(panel in COUNTS and type(case) is int and 0<=case<COUNTS[panel]//2
        and factors==factor_schedule(panel)[case] and type(ordinal) is int and 0<=ordinal<factors['clause_count'],
        'exact atom case/factors required')
    entity=f'{PREFIXES[panel]}{case:03d}x{ordinal}'
    modality='OPF'[('OPF'.index(factors['first_modality'])+ordinal)%3]
    kind=factors['preceding_time_kind'] if ordinal==0 else ('days','hours','calendar')[(case+ordinal)%3]
    duration={'none':None,'days':f'within {19+case%67} days','hours':f'within {31+case%59} hours',
        'calendar':f'before 2071-06-{1+case%28:02d}'}[kind]
    mask=({'C':1,'E':2,'CE':3}[factors['front_class']] if ordinal==1 else (case+ordinal)%4)
    rule={'modality':modality,'actor':f'the {entity} '+('Registry','Records Office','Dept. of Records')[(case+ordinal)%3],
        'action':temporal.VERBS[(case+ordinal)%len(temporal.VERBS)],'object':f'the {entity.lower()} filing packet',
        'conditions':[f'the {entity.lower()} permit is active'] if mask&1 else [],
        'exceptions':[f'the {entity.lower()} exemption is active'] if mask&2 else [],
        'temporal':[duration] if duration else []}
    w=temporal.prior.CoordinateWriter();notes=[];cues=[]
    def facet(field):
        value=rule[field];w.add(value[0] if isinstance(value,list) else value,field)
    def qualifier(field,cue='',suffix=''):
        start=len(w.text);w.add(cue)
        if cue:cues.append({'field':field,'start_char':start,'end_char':len(w.text),'source_text':cue})
        facet(field);w.add(suffix)
    def note():
        text=HEADINGS[(case//2+factors['variant'])%2];start=len(w.text);w.add(text)
        notes.append({'start_char':start,'end_char':len(w.text),'source_text':text,'author_stipulated_role':'nonoperative_editorial_context'})
    def front():
        fields=('conditions','exceptions') if factors['variant']%2==0 else ('exceptions','conditions')
        for field in fields:
            if rule[field]:
                cue=(('If ','When ','In cases where ') if field=='conditions' else ('Unless ','Except when ','Except where '))[(case+ordinal)%3]
                qualifier(field,cue,', ')
    if ordinal==1:
        for operation in {'train':('time','heading','front'),'tuning':('heading','time','front'),'fresh':('front','time','heading')}[panel]:
            if operation=='time':qualifier('temporal','',', ')
            elif operation=='heading':note()
            else:front()
    facet('actor')
    position=case%3
    if ordinal!=1 and duration and position==1:qualifier('temporal',', ',',')
    w.add(' ');w.add(temporal.TRIGGERS[modality][(case+ordinal)%2],'trigger')
    if ordinal!=1 and duration and position==2:qualifier('temporal',', ',',')
    w.add(' ');facet('action');w.add(' ');facet('object')
    if ordinal!=1:
        if rule['conditions']:qualifier('conditions',(' if ',' when ',' in cases where ')[case%3])
        if rule['exceptions']:qualifier('exceptions',(' unless ',' except when ',' except where ')[case%3])
        if duration and position==0:qualifier('temporal',' ')
    return {'source_text':w.text,'rule':rule,'facet_spans':{f:w.spans.get(f) for f in FIELDS},
        'trigger_span':w.spans['trigger'],'editorial_context':notes,'qualifier_cues':cues}


def _document(panel,case,factors,local,order,supported):
    text='';occurrences=[];declarations=[];attachment=None
    for index,original in enumerate(order):
        item=local[original]
        if index:
            if not supported and index==1:
                cue=(' unless ',' except when ',' except where ')[case%3];start=len(text);text+=cue
                attachment={'start_char':start,'end_char':len(text),'source_text':cue,'parent_occurrence':0,
                    'child_occurrence':1,'declared_relation':'nested_normative_exception_outside_flat_profile'}
            else:text+='\n' if case%2 else ' '
        start=len(text);text+=item['source_text'];end=len(text)
        occurrences.append({'index':index,'char_start':start,'char_end':end,'source_text':item['source_text'],
            'source_sha256':sha(item['source_text'].encode()),'rule':deepcopy(item['rule']),
            'facet_spans':{k:[start+x for x in v] if v else None for k,v in item['facet_spans'].items()},
            'trigger_span':[start+x for x in item['trigger_span']],
            'editorial_context':[{**v,'start_char':start+v['start_char'],'end_char':start+v['end_char']} for v in item['editorial_context']],
            'qualifier_cues':[{**v,'start_char':start+v['start_char'],'end_char':start+v['end_char']} for v in item['qualifier_cues']]})
        if supported or index!=0:text+='.'
        if supported:declarations.append({'char_start':start,'char_end':len(text),'rule':deepcopy(item['rule'])})
    digest=sha(text.encode());identity='scope-'+digest
    repeated=len({boundary.digest(v['rule']) for v in local})<len(local)
    row={'candidate_id':identity,'source_text':text,'source_sha256':digest,'supported':supported,
        'construction':factors['child_structure'] if supported else 'unsupported/nested_normative_exception',
        'repeated_rule_occurrences':repeated if supported else False,'clauses':declarations,
        'unsupported_reason':None if supported else 'nested_normative_exception','label_origin':'authored_scope_contrast_not_statutory_gold'}
    annotation={'candidate_id':identity,'source_sha256':digest,'panel':panel,
        'case_group':'case-'+sha(f'atom-boundary/{panel}/{case}'.encode()),'family':factors['child_structure'],
        'factors':deepcopy(factors),'body_order':list(order),'supported':supported,'side':'independent' if supported else 'nested',
        'local_clause_coordinates':occurrences,'scope_attachment':attachment,
        'annotation_authority':'author_stipulated_flat_profile_eligibility_not_semantic_truth'}
    validate_document(row,annotation)
    return row,annotation


def make_pair(panel,case):
    factors=factor_schedule(panel)[case]
    local=[render_local(panel,case,i,factors) for i in range(factors['clause_count'])]
    if factors['clause_count']==3 and case%4==3:local[2]=deepcopy(local[0])
    order=list(range(len(local)))
    left,la=_document(panel,case,factors,local,order,True)
    right,ra=_document(panel,case,factors,local,[order[-1]]+order[:-1] if panel=='train' else order,panel=='train')
    pair={'pair_id':'pair-'+sha(la['case_group'].encode()),'local_clause_body_sha256':[sha(v['source_text'].encode()) for v in local]}
    pair.update({'forward_id':left['candidate_id'],'rotated_id':right['candidate_id']} if panel=='train'
        else {'case_group':la['case_group'],'independent_id':left['candidate_id'],'nested_id':right['candidate_id']})
    return [left,right],pair,[la,ra]


def validate_document(row,annotation=None):
    previous.validate_document(row,annotation)
    require(row['candidate_id']=='scope-'+row['source_sha256'],'opaque exact-source identity required')
    boundary.tokenize(row['source_text'])
    if annotation is None:return
    f=annotation['factors'];order=annotation['body_order'];occ=annotation['local_clause_coordinates']
    require(set(f)==FACTOR_KEYS and f['child_structure']==STRUCTURES[annotation['panel']]
        and f['front_class'] in FRONT_CLASSES and f['preceding_time_kind'] in TIME_KINDS,
        'closed declared atom factors differ')
    require(len(occ)==f['clause_count'] in (2,3) and sorted(order)==list(range(len(occ))),'body permutation differs')
    first=occ[order.index(0)];wanted=f['preceding_time_kind'];time=first['rule']['temporal']
    require(first['rule']['modality']==f['first_modality'] in 'OPF','canonical first modality differs')
    if wanted=='none':require(time==[],'absent preceding time differs')
    else:
        pattern={'days':r'within \d+ days','hours':r'within \d+ hours','calendar':r'before \d{4}-\d{2}-\d{2}'}[wanted]
        require(len(time)==1 and re.fullmatch(pattern,time[0]),'preceding temporal kind differs')
    if row['supported']:
        require(all(c['char_start']==o['char_start'] and c['char_end']==o['char_end']+1
            and c['rule']==o['rule'] and row['source_text'][o['char_end']]=='.'
            for c,o in zip(row['clauses'],occ,strict=True)),'exact occurrence boundaries/rules differ')
    child=occ[order.index(1)];notes=child['editorial_context'];spans=child['facet_spans']
    require(len(notes)==1 and notes[0]['source_text'] in HEADINGS and spans['temporal'] is not None,'child heading/time required')
    fields=[k for k in ('conditions','exceptions') if spans[k]]
    require(fields=={'C':['conditions'],'E':['exceptions'],'CE':['conditions','exceptions']}[f['front_class']],
        'fronted C/E presence differs')
    ranges={'time':spans['temporal'],'heading':[notes[0]['start_char'],notes[0]['end_char']],
        'qualifiers':[min(spans[k][0] for k in fields),max(spans[k][1] for k in fields)],'actor':spans['actor']}
    realized='_'.join(sorted(ranges,key=lambda k:ranges[k][0]))
    require(realized==f['child_structure'],'realized role order differs')
    for local in occ:
        for note in local['editorial_context']:
            require(row['source_text'][note['start_char']:note['end_char']]==note['source_text'],'exact editorial span differs')
        for cue in local['qualifier_cues']:
            require(row['source_text'][cue['start_char']:cue['end_char']]==cue['source_text']
                and cue['end_char']==local['facet_spans'][cue['field']][0],'direct cue ownership differs')


def validate_training_pairs(rows,pairs):
    require(len(rows)==144 and len(pairs)==72,'exact144 supported augmentation/72pairs required')
    lookup={r['candidate_id']:r for r in rows};seen=set()
    require(len(lookup)==144 and all(r['supported'] for r in rows),'unique supported augmentation required')
    for pair in pairs:
        require(set(pair)==TRAIN_PAIR_KEYS,'closed source-order contrast pair required')
        ids=(pair['forward_id'],pair['rotated_id'])
        require(ids[0]!=ids[1] and all(i in lookup and i not in seen for i in ids),'unique TRAIN pair membership required')
        bodies=[]
        for identity in ids:
            row=lookup[identity];validate_document(row)
            bodies.append([sha(row['source_text'][c['char_start']:c['char_end']-1].encode()) for c in row['clauses']])
        require(bodies[0]==pair['local_clause_body_sha256'] and bodies[1]==bodies[0][-1:]+bodies[0][:-1],
            'exact same local bodies and last-first rotation required')
        left,right=(lookup[i] for i in ids)
        require([c['rule'] for c in right['clauses']]==[c['rule'] for c in left['clauses']][-1:]+[c['rule'] for c in left['clauses']][:-1],
            'canonical meaning rotation differs')
        seen.update(ids)
    require(seen==set(lookup) and len({p['pair_id'] for p in pairs})==72,'complete unique TRAIN pairs required')


def make_panels():
    panels={};pairs={};annotations=[];counts={}
    for panel,count in COUNTS.items():
        rows=[];labels=[];pairs[panel]=[]
        for case in range(count//2):
            rr,pp,aa=make_pair(panel,case);rows.extend(rr);pairs[panel].append(pp);labels.extend(aa)
        random.Random(SHUFFLE_SEED+list(COUNTS).index(panel)).shuffle(rows)
        if panel=='train':validate_training_pairs(rows,pairs[panel])
        else:previous.validate_pairs(rows,pairs[panel],count//2)
        panels[panel]=rows;annotations.extend(labels)
        counts[panel]={'documents':count,'supported':sum(r['supported'] for r in rows),'unsupported':sum(not r['supported'] for r in rows),
            'pairs':len(pairs[panel]),'factor_counts':{k:dict(Counter(str(a['factors'][k]) for a in labels)) for k in sorted(FACTOR_KEYS)},
            'max_source_tokens':max(len(boundary.tokenize(r['source_text'])) for r in rows)}
    normalized=[temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows]
    require(len(normalized)==len(set(normalized))==432,'new source split overlap')
    meanings=[{boundary.digest(o['rule']) for a in annotations if a['panel']==p for o in a['local_clause_coordinates']} for p in COUNTS]
    require(not any(a&b for i,a in enumerate(meanings) for b in meanings[i+1:]),'new meanings cross splits')
    ledger={'schema':'legal-atom-boundary-annotations/v1','document_rows':annotations}
    return panels,pairs,ledger,counts


def training_atom_roles(rows,annotations=None):
    lookup={a['candidate_id']:a for a in (annotations or {}).get('document_rows',[])}
    result=[]
    for row in rows:
        require(row['supported'] is True,'unsupported rows excluded from atom supervision')
        tokens=boundary.tokenize(row['source_text']);ends={c['char_end'] for c in row['clauses']}
        require(ends and ends<={t['char_end'] for t in tokens} and max(ends)==len(row['source_text'].rstrip()),'complete supported endpoints required')
        spans=[]
        for clause in row['clauses']:
            body=row['source_text'][clause['char_start']:clause['char_end']]
            for field in ATOM_FIELDS:
                values=clause['rule'][field];values=[values] if isinstance(values,str) else values
                require(type(values) is list and len(values)<=1,'flat zero-or-one atom per field required')
                for value in values:
                    starts=[m.start() for m in re.finditer(re.escape(value),body)]
                    require(len(starts)==1,'canonical atom must occur uniquely inside its own clause')
                    start=clause['char_start']+starts[0];spans.append({'kind':field,'char_start':start,'char_end':start+len(value)})
        spans.sort(key=lambda x:(x['char_start'],x['char_end'],x['kind']))
        require(all(a['char_end']<=b['char_start'] for a,b in zip(spans,spans[1:])),'copied atom roles overlap')
        if row['candidate_id'] in lookup:
            annotation=lookup[row['candidate_id']];previous.validate_document(row,annotation)
            authored=sorted(({'kind':k,'char_start':o['facet_spans'][k][0],'char_end':o['facet_spans'][k][1]}
                for o in annotation['local_clause_coordinates'] for k in ATOM_FIELDS if o['facet_spans'][k]),key=lambda x:(x['char_start'],x['char_end'],x['kind']))
            require(authored==spans,'insertion-time atoms differ from canonical source reconstruction')
        positive=[i for i,t in enumerate(tokens) if t['char_end'] in ends-{max(ends)}]
        negative=[i for i,t in enumerate(tokens) if t['char_end'] not in ends and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in spans)]
        require(negative and (positive or len(row['clauses'])==1),'source-bound atom negatives required')
        result.append({'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],
            'inter_clause_end_token_indices':positive,'atom_interior_negative_token_indices':negative,
            'atom_spans':spans,'provenance':ATOM_PROVENANCE})
    return result


def atom_role_counts(records):
    return {'documents':len(records),'inter_clause_end_tokens':sum(len(r['inter_clause_end_token_indices']) for r in records),
        'atom_interior_negative_tokens':sum(len(r['atom_interior_negative_token_indices']) for r in records),
        'span_counts':dict(Counter(s['kind'] for r in records for s in r['atom_spans']))}


def historical_inventory(heading_manifest_path=DEFAULT_HEADING):
    pin=file_ref(heading_manifest_path);parent=read_ref(pin)
    require(parent['schema']==heading.SCHEMA,'pinned previous heading corpus required')
    history=heading.historical_inventory(parent['inputs']['prior_preservation_corpus']['path'])
    ledger=read_ref(parent['artifacts']['annotation_ledger']);lookup={a['candidate_id']:a for a in ledger['document_rows']}
    for name,key in (('prior_heading_tuning','tuning_targets'),('prior_heading_fresh','fresh_targets')):
        ref=parent['artifacts'][key];rows=read_ref(ref)
        history['document_references'][name]=ref;history['pools'][name]=rows
        history['excluded_sources'].update(r['source_text'] for r in rows)
        history['layout_rows'][name]=[{'candidate_id':r['candidate_id'],'source_sha256':r['source_sha256'],
            'role_masked_layout':previous.role_layout(r,lookup[r['candidate_id']])} for r in rows]
        history['unannotated_unsupported_ids'][name]=[]
    history['retention_target_references']={**parent['retention_target_references'],
        'prior_heading_tuning':parent['artifacts']['tuning_targets'],'prior_heading_fresh':parent['artifacts']['fresh_targets']}
    history['annotation_references']['prior_heading']=parent['artifacts']['annotation_ledger']
    history['annotation_ledgers']['prior_heading']=ledger
    history.update(prior_heading_manifest=parent,prior_heading_manifest_ref=pin)
    require(len(history['retention_target_references'])==21,'complete21 historical panels required')
    return history


def exposure_payload(history,panels,ledger):
    oldtexts={temporal.prior.normalized_source(s) for s in history['excluded_sources']}
    newtexts={temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows}
    require(not oldtexts&newtexts,'new source overlaps exposed history')
    oldrules={boundary.digest(c['rule']) for rows in history['pools'].values() for r in rows for c in r['clauses']}
    newrules={boundary.digest(o['rule']) for a in ledger['document_rows'] for o in a['local_clause_coordinates']}
    require(not oldrules&newrules,'new canonical local meanings overlap history')
    lookup={a['candidate_id']:a for a in ledger['document_rows']}
    known={k:{r['role_masked_layout'] for r in v} for k,v in history['layout_rows'].items()}
    for panel in ('train','tuning'):known['new_'+panel]={previous.role_layout(r,lookup[r['candidate_id']]) for r in panels[panel]}
    evidence=[]
    for row in panels['fresh']:
        a=lookup[row['candidate_id']];layout=previous.role_layout(row,a);matches=sorted(k for k,v in known.items() if layout in v)
        require(not matches,'fresh full structural role layout already exposed; no silent novelty relabeling')
        evidence.append({'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'case_group':a['case_group'],
            'role_masked_layout':layout,'matching_pools':matches,'layout_status':'unmatched_audited_combination',
            'child_structure':a['factors']['child_structure']})
    return {'schema':'legal-atom-boundary-exposure/v1','rows':evidence,'known_role_masked_layouts':{k:sorted(v) for k,v in known.items()},
        'historical_layout_rows':history['layout_rows'],'historical_unannotated_unsupported_ids':history['unannotated_unsupported_ids'],
        'historical_document_references':history['document_references'],'historical_annotation_references':history['annotation_references'],
        'prior_condition_single_references':history['condition_single_references'],'prior_source_references':history['prior_source_references'],
        'historical_source_inventory_count':len(oldtexts),'historical_source_inventory_sha256':boundary.digest(sorted(oldtexts)),
        'real_exposed_views':history['real_exposed_views'],'new_source_overlap_count':0,'declared_child_structures':STRUCTURES,
        'claim':'New source/case/local meaning groups; individual cues and heading markers shared. Fresh child qualifier-time-heading order and full role layouts withheld from new TRAIN/tuning; full layouts unmatched against pinned historical local inventories. Unannotated old guards cannot establish universal novelty. Authored scope only, not legal gold.'}


def freeze(output,heading_manifest_path=DEFAULT_HEADING):
    output=Path(output).resolve();require(not output.exists(),'new output directory required')
    history=historical_inventory(heading_manifest_path);parent=history['prior_heading_manifest']
    loaded=heading.load_training_inputs(heading_manifest_path)
    panels,pairs,ledger,counts=make_panels();exposure=exposure_payload(history,panels,ledger)
    trainledger={**ledger,'document_rows':[a for a in ledger['document_rows'] if a['panel']=='train']}
    evalledger={**ledger,'document_rows':[a for a in ledger['document_rows'] if a['panel']!='train']}
    fit=loaded['boundary_training']+panels['train']
    roles=loaded['training_token_roles']+heading.training_token_roles(panels['train'],{'new_train':trainledger})
    atomroles=training_atom_roles(fit,trainledger)
    output.mkdir(parents=True)
    artifacts={k:parent['artifacts'][k] for k in ('new_training_targets','training_pairs','training_sources')}
    for key,filename,value in (('atom_training_targets','atom-training-targets.json',panels['train']),
        ('atom_training_pairs','atom-training-pairs.json',pairs['train']),('atom_training_sources','atom-training-sources.json',[source_row(r) for r in panels['train']]),
        ('training_annotation_ledger','training-annotations.json',trainledger),('training_token_roles','training-token-roles.json',roles),
        ('training_atom_roles','training-atom-roles.json',atomroles)):
        artifacts[key]=write_new(output/filename,value)
    for panel in ('tuning','fresh'):
        suffix='.sealed.json' if panel=='fresh' else '.json'
        for kind,value in (('targets',panels[panel]),('pairs',pairs[panel])):
            key=panel+'_'+kind;artifacts[key]=write_new(output/(key.replace('_','-')+suffix),value)
        key=panel+'_sources';artifacts[key]=write_new(output/(key.replace('_','-')+'.json'),[source_row(r) for r in panels[panel]])
    artifacts['annotation_ledger']=write_new(output/'annotations.sealed.json',evalledger)
    artifacts['exposure_audit']=write_new(output/'exposure-audit.sealed.json',exposure)
    manifest={'schema':SCHEMA,'generator':file_ref(__file__),'frozen_before_training':True,
        'dependencies':{k:file_ref(v.__file__) for k,v in (('heading_corpus',heading),('previous_scope',previous),('temporal_corpus',temporal),('boundary_decoder',boundary))},
        'inputs':{'prior_heading_corpus':history['prior_heading_manifest_ref']},'artifacts':artifacts,
        'replay_references':parent['replay_references'],'retention_target_references':history['retention_target_references'],
        'training_annotation_references':parent['training_annotation_references'],'counts':counts,
        'historical_training_documents':1152,'training_documents':1296,'supervised_training_documents':864,
        'excluded_unsupported_training_documents':432,'new_training_documents':144,'historical_training_reused_without_changes':True,
        'training_token_role_counts':heading.role_counts(roles),'training_atom_role_counts':atom_role_counts(atomroles),
        'source_order_seed':SHUFFLE_SEED,'sealed_artifacts':list(SEALED),'training_performed':False,
        'source_semantics_verified':False,'statutory_gold_available':False,
        'scope':'Same720 historical supported rows plus144 new authored supported rotation contrasts; no unsupported endpoint supervision; held-out role-order evaluation.'}
    return write_new(output/'manifest.json',manifest)


def load_training_inputs(manifest_path):
    """Open only admitted TRAIN/tuning and current fresh sources; never sealed refs."""
    m=read_ref(file_ref(manifest_path));require(m['schema']==SCHEMA and m['frozen_before_training'] is True
        and m['sealed_artifacts']==list(SEALED),'frozen atom corpus/seals required')
    verify_ref(m['generator'])
    for pin in list(m['dependencies'].values())+list(m['inputs'].values()):verify_ref(pin)
    loaded=heading.load_training_inputs(m['inputs']['prior_heading_corpus']['path']);parent=loaded['manifest'];a=m['artifacts']
    require(m['replay_references']==parent['replay_references'] and all(a[k]==parent['artifacts'][k] for k in ('new_training_targets','training_pairs','training_sources')),
        'historical TRAIN references changed')
    expected={**parent['retention_target_references'],'prior_heading_tuning':parent['artifacts']['tuning_targets'],'prior_heading_fresh':parent['artifacts']['fresh_targets']}
    require(m['retention_target_references']==expected and m['training_annotation_references']==parent['training_annotation_references'],
        'historical retention or annotation ancestry changed')
    require(set(m['counts'])==set(COUNTS) and all(m['counts'][p]['documents']==n and m['counts'][p]['pairs']==n//2
        and m['counts'][p]['supported']==(n if p=='train' else n//2) and m['counts'][p]['unsupported']==(0 if p=='train' else n//2)
        for p,n in COUNTS.items()),'complete authored panel denominators differ')
    train=read_ref(a['atom_training_targets']);pairs=read_ref(a['atom_training_pairs']);validate_training_pairs(train,pairs)
    require(read_ref(a['atom_training_sources'])==[source_row(r) for r in train],'new TRAIN source order differs')
    ledger=read_ref(a['training_annotation_ledger']);annotations=ledger['document_rows']
    require(ledger['schema']=='legal-atom-boundary-annotations/v1' and len(annotations)==144
        and {v['candidate_id'] for v in annotations}=={r['candidate_id'] for r in train}
        and all(v['panel']=='train' for v in annotations),'TRAIN-only direct annotation inventory required')
    lookup={v['candidate_id']:v for v in annotations}
    for row in train:validate_document(row,lookup[row['candidate_id']])
    fit=loaded['boundary_training']+train
    roles=read_ref(a['training_token_roles']);atomroles=read_ref(a['training_atom_roles'])
    require(roles==loaded['training_token_roles']+heading.training_token_roles(train,{'new_train':ledger})
        and atomroles==training_atom_roles(fit,ledger),'exact TRAIN-only source-bound masks differ')
    require(m['training_token_role_counts']==heading.role_counts(roles) and m['training_atom_role_counts']==atom_role_counts(atomroles),
        'TRAIN role counts differ')
    require((m['historical_training_documents'],m['training_documents'],m['supervised_training_documents'],m['excluded_unsupported_training_documents'],m['new_training_documents'])==(1152,1296,864,432,144)
        and m['historical_training_reused_without_changes'] is True and m['source_order_seed']==SHUFFLE_SEED,'training denominator differs')
    tune=read_ref(a['tuning_targets']);tpairs=read_ref(a['tuning_pairs']);previous.validate_pairs(tune,tpairs,48)
    require(read_ref(a['tuning_sources'])==[source_row(r) for r in tune],'tuning source order differs')
    fresh=read_ref(a['fresh_sources']);legacy.validate_sources(fresh,192)
    for r in [source_row(r) for r in train+tune]+fresh:
        require(set(r)==SOURCE_KEYS and r['candidate_id']=='scope-'+sha(r['source_text'].encode()) and r['source_sha256']==sha(r['source_text'].encode()),
            'opaque closed source rows required')
        boundary.tokenize(r['source_text'])
    tuning={k:read_ref(v) for k,v in expected.items()};tuning['atom_new']=tune
    require(len(tuning)==22 and sum(map(len,tuning.values()))==2448,'all22 admitted tuning panels2448 required')
    old=[r for rows in loaded['replay'].values() for r in rows]+loaded['new_train']
    hashes={r['source_sha256'] for r in train+tune+fresh}
    priorhashes={r['source_sha256'] for rows in [old]+[v for k,v in tuning.items() if k!='atom_new'] for r in rows}
    require(len(hashes)==432 and not hashes&priorhashes and len({r['source_sha256'] for r in old})==1152,'new sources overlap history or split')
    for rows in tuning.values():legacy.validate_references(rows,len(rows),sum(r['supported'] for r in rows))
    return {'manifest':m,'replay':loaded['replay'],'new_train':loaded['new_train'],'training_pairs':loaded['training_pairs'],
        'atom_train':train,'atom_training_pairs':pairs,'boundary_training':fit,'supported_replay':loaded['supported_replay'],
        'supported_heading':loaded['supported_heading'],'training_token_roles':roles,'training_atom_roles':atomroles,
        'training_annotation_ledger':ledger,'new_tuning':tune,'tuning_pairs':tpairs,'tuning':tuning,'fresh_sources':fresh}


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--prior-heading-manifest',default=str(DEFAULT_HEADING));args=parser.parse_args()
    print(json.dumps(freeze(args.output,args.prior_heading_manifest),sort_keys=True))
