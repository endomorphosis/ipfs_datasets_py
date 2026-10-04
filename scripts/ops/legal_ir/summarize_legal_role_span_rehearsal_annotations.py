"""Pure post-release audit of authored role-span supervision and exposure.

No file reads, model execution or semantic-gold claims. The caller supplies the
67 historical pools: old temporal.historical_inputs pools, main_training,
legacy_tuning_*, legacy_retention_*, prior_condition, oracle_{atom_tuning,
atom_fresh,prior_condition}, and old_document_* reconstructed from the atom
manifest's 21 retention references. Historical source inventory additionally
contains the complete legacy single/document sources, old atom/condition full
documents and real86 diagnostic views. Current auxiliary/tuning pools are
added independently here. Pinned references are verified by the caller.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import re

FIELDS=('actor','action','object','conditions','exceptions','temporal')
ROW_KEYS={'id','source_text','canonical_ir','trigger_span','facet_spans','domain','trigger_supervised'}
PAIR_KEYS={'pair_id','case_group','left_id','right_id','canonical_ir_sha256'}
CAPTIONS=('(2) Filing duty: ','Record duty [2]. ','Editorial index [section 63001.2]: ')
FAMILIES=('caption_presence','caption_displacement','front_interposed','interposed_trailing')
TRIGGERS={'shall':'O','must':'O','may':'P','is permitted to':'P','must not':'F','may not':'F'}
ALL_MODALS=('shall','must','may','shall not','must not','may not','is allowed to','has a duty to',
    'has permission to','is forbidden to','is required to','is permitted to','is not permitted to')
SINGLE_COUNTS={'train':576,'tuning':192,'fresh':192}
OCCURRENCE_KEYS={'id','document_id','document_source_sha256','source_sha256','char_start','char_end','occurrence_index'}
AUTHORITY='authored_controlled_example_not_statutory_gold'


def require(condition,message):
    if not condition:raise ValueError(message)


def text_sha(text):return hashlib.sha256(text.encode()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def normalize(text):return ' '.join(re.findall(r'\w+|[^\w\s]',text.casefold()))


def independent_layout(row):
    text=row['source_text'];parts=[];cursor=0
    for start,end,field in sorted((span[0],span[1],field) for field,span in row['facet_spans'].items() if span is not None):
        require(type(start) is int and type(end) is int and cursor<=start<end<=len(text),'layout role coordinates overlap or escape source')
        parts.extend((text[cursor:start],'<'+field+'>'));cursor=end
    parts.append(text[cursor:]);layout=''.join(parts).casefold()
    layout=re.sub(r'\b\d+\b','#',layout);layout=re.sub(r'(?<=\()\w(?=\))','#',layout)
    layout=' '.join(layout.split())
    for cue in sorted(ALL_MODALS,key=len,reverse=True):layout=re.sub(r'\b'+re.escape(cue)+r'\b','<modal>',layout)
    return layout.rstrip('.;')


def mask(row):return sum(1<<bit for bit,f in enumerate(FIELDS[3:]) if row['canonical_ir']['rules'][0][f])


def validate_coordinates(row):
    require(type(row) is dict and set(row)==ROW_KEYS and row['domain']=='new' and row['trigger_supervised'] is True,'closed new-domain role row required')
    source=row['source_text'];rule=row['canonical_ir']
    require(type(source) is str and source and set(rule)=={'rules'} and len(rule['rules'])==1,'one authored complete rule required')
    rule=rule['rules'][0]
    require(set(rule)=={'modality',*FIELDS} and rule['modality'] in 'OPF' and set(row['facet_spans'])==set(FIELDS),'closed rule/facet inventory required')
    tokens=list(re.finditer(r'\w+|[^\w\s]',source));starts={t.start() for t in tokens};ends={t.end() for t in tokens}
    require(1<=len(tokens)<=256,'single clause token bounds exceeded')
    intervals=[]
    for field in FIELDS:
        value=rule[field]
        if field in FIELDS[3:]:
            require(type(value) is list and len(value)<=1,'at most one atom per optional facet')
            value=value[0] if value else None
        else:require(type(value) is str and bool(value),'nonempty mandatory copied atom required')
        span=row['facet_spans'][field]
        if value is None:require(span is None,'absent facet has a pointer');continue
        require(type(span) is list and len(span)==2 and all(type(v) is int for v in span),'two exact character coordinates required')
        start,end=span
        require(start in starts and end in ends and start<end and source[start:end]==value,'copied atom does not match exact token-aligned source')
        require(len(list(re.finditer(re.escape(value),source)))==1,'copied atom must be unique within this local occurrence')
        intervals.append((start,end,field))
    span=row['trigger_span'];require(type(span) is list and len(span)==2,'trigger coordinates required')
    start,end=span
    require(type(start) is int and type(end) is int and start in starts and end in ends and start<end
            and TRIGGERS.get(source[start:end])==rule['modality'],'explicit authored modal force differs')
    intervals.append((start,end,'trigger'));intervals.sort()
    require(all(left[1]<=right[0] for left,right in zip(intervals,intervals[1:])),'role or trigger intervals overlap')
    return intervals


def captions_in_source(row):
    result=[]
    for text in CAPTIONS:
        for match in re.finditer(re.escape(text),row['source_text']):
            result.append({'start_char':match.start(),'end_char':match.end(),'source_text':text,
                           'author_stipulated_role':'nonoperative_editorial_context'})
    return sorted(result,key=lambda n:n['start_char'])


def declared_order(family,side,panel):
    profiles={
        'caption_presence':(('conditions','exceptions','temporal','actor','trigger','action','object'),
            ('conditions','exceptions','temporal','heading','actor','trigger','action','object')),
        'caption_displacement':(('heading','temporal','exceptions','conditions','actor','trigger','action','object'),
            ('temporal','exceptions','conditions','heading','actor','trigger','action','object')),
        'front_interposed':(('conditions','exceptions','temporal','heading','actor','trigger','action','object'),
            ('temporal','heading','actor','conditions','trigger','exceptions','action','object')),
        'interposed_trailing':(('exceptions','heading','actor','temporal','trigger','conditions','action','object'),
            ('heading','actor','trigger','action','object','conditions','exceptions','temporal'))}
    if side==1 and panel=='tuning' and family=='front_interposed':return ('exceptions','temporal','heading','actor','trigger','conditions','action','object')
    if side==1 and panel=='tuning' and family=='interposed_trailing':return ('heading','conditions','actor','exceptions','trigger','action','object','temporal')
    if side==1 and panel=='fresh' and family=='front_interposed':return ('conditions','heading','actor','exceptions','trigger','temporal','action','object')
    if side==1 and panel=='fresh' and family=='interposed_trailing':return ('heading','temporal','actor','trigger','exceptions','action','object','conditions')
    return profiles[family][side]


def audit_single(row,annotation,panel):
    intervals=validate_coordinates(row);source=row['source_text'];a=annotation
    require(row['id']=='role-'+text_sha(source) and a['id']==row['id'] and a['source_sha256']==text_sha(source)
            and a['panel']==panel and a['family'] in FAMILIES and a['side'] in (0,1)
            and a['annotation_authority']==AUTHORITY,'closed single source/annotation lineage differs')
    require(a['facet_spans']==row['facet_spans'] and a['trigger_span']==row['trigger_span'] and a['presence_mask']==mask(row),'direct annotated role spans differ')
    layout=independent_layout(row)
    require(a['role_masked_layout']==layout and a['layout_sha256']==text_sha(layout),'independent source layout differs')
    notes=captions_in_source(row)
    require(a['editorial_context']==notes and len(notes)==(0 if a['family']=='caption_presence' and a['side']==0 else 1),'editorial span provenance or headedness differs')
    require(type(a['caption_style']) is int and a['caption_style'] in range(3)
            and all(n['source_text']==CAPTIONS[a['caption_style']] for n in notes),'caption style differs from literal source')
    for note in notes:
        require(all(end<=note['start_char'] or start>=note['end_char'] for start,end,_ in intervals),'editorial caption crosses copied semantic role')
    positioned={field:span[0] for field,span in row['facet_spans'].items() if span is not None}
    positioned['trigger']=row['trigger_span'][0]
    if notes:positioned['heading']=notes[0]['start_char']
    require(tuple(sorted(positioned,key=positioned.get))==tuple(field for field in declared_order(a['family'],a['side'],panel) if field in positioned),
            'realized caption/qualifier/actor/modal order differs from declared contrast')
    expected_cues=[]
    for field,cues in (('conditions',('provided that','when','if')),('exceptions',('except when','except where','unless'))):
        span=row['facet_spans'][field]
        if span:
            choices=[cue+' ' for cue in cues if source[:span[0]].endswith(cue+' ')]
            require(len(choices)==1,'qualifier attachment cue missing or ambiguous')
            cue=choices[0];expected_cues.append({'field':field,'start_char':span[0]-len(cue),'end_char':span[0],'source_text':cue})
    require(a['qualifier_cues']==sorted(expected_cues,key=lambda q:q['start_char']),'qualifier cue inventory differs from source')
    rule=row['canonical_ir']['rules'][0];opaque=not rule['temporal'] and any(' application was received within ' in x for x in rule['conditions'])
    require(a['condition_owned_temporal_language'] is opaque,'opaque condition timing declaration differs')
    kind=None
    if rule['temporal']:
        literal=rule['temporal'][0]
        kind='days' if re.fullmatch(r'within \d+ days',literal) else 'hours' if re.fullmatch(r'within \d+ hours',literal) else 'calendar' if re.fullmatch(r'before \d{4}-\d{2}-\d{2}',literal) else None
        require(kind is not None,'unrecognized declared closed temporal form')
    require(a['temporal_kind']==kind,'temporal kind declaration differs')
    return layout


def audit_pairs(rows,pairs,annotations):
    lookup={r['id']:r for r in rows};used=set();cases=set()
    require(len(lookup)==len(rows)==2*len(pairs),'complete pair inventory required')
    for p in pairs:
        require(type(p) is dict and set(p)==PAIR_KEYS,'closed five-key semantic pair required')
        ids=(p['left_id'],p['right_id'])
        require(len(set(ids))==2 and set(ids)<=set(lookup) and not used.intersection(ids),'same-meaning pair membership reused or missing')
        left,right=(lookup[i] for i in ids);la,ra=(annotations[i] for i in ids)
        require(left['canonical_ir']==right['canonical_ir'] and digest(left['canonical_ir'])==p['canonical_ir_sha256']
                and left['source_text']!=right['source_text'],'pair semantics differ or surfaces collapse')
        require(la['case_group']==ra['case_group']==p['case_group']==p['pair_id'] and p['case_group'] not in cases
                and (la['side'],ra['side'])==(0,1) and la['family']==ra['family'] and la['caption_style']==ra['caption_style'], 'pair role/factor/case metadata differs')
        used.update(ids);cases.add(p['case_group'])
    require(used==set(lookup),'semantic pair inventory not exhaustive')
    return cases


def audit_blocks(rows,pairs,blocks,annotations):
    lookup={r['id']:r for r in rows};pairmap={p['pair_id']:p for p in pairs};used=[]
    require(len(blocks)==144 and len({b['block_id'] for b in blocks})==144,'144 unique complement blocks required')
    for block in blocks:
        require(set(block)=={'block_id','pair_ids'} and len(block['pair_ids'])==len(set(block['pair_ids']))==2
                and block['block_id']=='block-'+digest(block['pair_ids']),'closed content-bound block required')
        require(set(block['pair_ids'])<=set(pairmap),'unknown pair in block')
        selected=[lookup[pairmap[p][side]] for p in block['pair_ids'] for side in ('left_id','right_id')]
        require(len({r['id'] for r in selected})==4 and mask(selected[0])^mask(selected[2])==7,'four distinct complementary-mask rows required')
        require(all(sum(bool(r['canonical_ir']['rules'][0][field]) for r in selected)==2 for field in FIELDS[3:]), 'C/E/T presence must each be2/2')
        require(len({r['canonical_ir']['rules'][0]['modality'] for r in selected})==1
                and len({annotations[r['id']]['family'] for r in selected})==1
                and len({annotations[r['id']]['caption_style'] for r in selected})==1,'complement blocks must share modal/layout/caption factors')
        used.extend(block['pair_ids'])
    require(len(used)==len(set(used))==len(pairs) and set(used)==set(pairmap),'block pair coverage differs')


def local_row(document,coordinate,end,identity):
    start=coordinate['char_start']
    return {'id':identity,'source_text':document['source_text'][start:end],
        'canonical_ir':{'rules':[deepcopy(coordinate['rule'])]},
        'facet_spans':{f:[v-start for v in span] if span else None for f,span in coordinate['facet_spans'].items()},
        'trigger_span':[v-start for v in coordinate['trigger_span']],'domain':'new','trigger_supervised':True}


def audit_documents(documents,pairs,annotations,panel):
    rows={r['candidate_id']:r for r in documents};labels={a['candidate_id']:a for a in annotations};used=set();cases=set();local_targets=[]
    require(len(rows)==len(documents)==len(labels)==96 and len(pairs)==48,'complete96document48pair inventory required')
    require(Counter(r['supported'] for r in documents)=={True:48,False:48},'all guards and supported denominators required')
    for pair in pairs:
        require(set(pair)=={'pair_id','case_group','independent_id','nested_id','local_clause_body_sha256'},'closed document contrast pair required')
        ids=(pair['independent_id'],pair['nested_id'])
        require(len(set(ids))==2 and set(ids)<=set(rows) and not used.intersection(ids),'scope pair membership reused or missing')
        variants=[]
        for identity,supported in zip(ids,(True,False),strict=True):
            row=rows[identity];a=labels[identity];source=row['source_text'];coordinates=a['local_clause_coordinates']
            require(identity=='document-'+text_sha(source) and row['source_sha256']==a['source_sha256']==text_sha(source)
                    and row['supported'] is a['supported'] is supported and a['panel']==panel
                    and a['case_group']==pair['case_group'] and a['annotation_authority']==AUTHORITY,'document source/case binding differs')
            require(row['unsupported_reason']==(None if supported else 'nested_normative_exception')
                    and len(row['clauses'])==(len(coordinates) if supported else 0) and len(coordinates) in (2,3),'explicit unsupported scope inventory differs')
            bodies=[];rules=[];cursor=0
            for index,coordinate in enumerate(coordinates):
                start,end=coordinate['char_start'],coordinate['char_end'];require(coordinate['occurrence_index']==index and cursor<=start<end<=len(source),'document interval order differs')
                gap=source[cursor:start]
                if not supported and index==1:
                    attachment=a['scope_attachment']
                    require(gap in (' unless ',' except when ',' except where ') and attachment=={'start_char':cursor,'end_char':start,'source_text':gap,
                            'parent_occurrence':0,'child_occurrence':1,'declared_relation':'nested_normative_exception_outside_flat_profile'},'nested relation interval differs')
                else:require(not gap.strip(),'non-whitespace uncovered between independent bodies')
                terminal=supported or index!=0
                require(not terminal or source[end:end+1]=='.','complete authored terminal punctuation required')
                local=local_row(row,coordinate,end+int(terminal),'oracle-validation')
                validate_coordinates(local);notes=captions_in_source(local)
                expected=[{**n,'start_char':n['start_char']+start,'end_char':n['end_char']+start} for n in notes]
                require(coordinate['editorial_context']==expected and coordinate['presence_mask']==mask(local),'document role/editorial direct provenance differs')
                for note in expected:
                    require(all(span is None or span[1]<=note['start_char'] or span[0]>=note['end_char'] for span in coordinate['facet_spans'].values()),'document caption crosses copied role')
                if supported:
                    require(row['clauses'][index]=={'char_start':start,'char_end':end+1,'rule':coordinate['rule']},'declared positive endpoint/rule differs from local body')
                    local_targets.append(local)
                bodies.append(text_sha(source[start:end]));rules.append(coordinate['rule']);cursor=end+int(terminal)
            require(not source[cursor:].strip(),'uncovered document tail')
            repeated=supported and len({digest(r) for r in rules})<len(rules)
            require(row['repeated_rule_occurrences'] is repeated and (not supported or a['scope_attachment'] is None),'occurrence multiplicity or independent scope differs')
            require('provided that' not in source,'provided-that deliberately excluded from supported document grammar')
            variants.append((bodies,rules))
        require(variants[0]==variants[1] and variants[0][0]==pair['local_clause_body_sha256'],'scope contrast changed exact local bodies/meanings')
        require(pair['case_group'] not in cases,'document case reused across pairs')
        cases.add(pair['case_group']);used.update(ids)
    require(used==set(rows) and len(local_targets)==120,'all document occurrences must survive scope auditing')
    require(Counter(len(r['clauses']) for r in documents if r['supported'])=={2:24,3:24}
            and sum(r['repeated_rule_occurrences'] for r in documents)==6,'document count/repetition schedule differs')
    return cases,local_targets


def audit_oracle_targets(documents,annotations,targets,pack):
    docs={r['candidate_id']:r for r in documents if r['supported']};labels={a['candidate_id']:a for a in annotations}
    sources,mapping,plans,doc_sources=(pack[k] for k in ('sources','occurrences','boundaries','document_sources'))
    require(doc_sources==[{k:r[k] for k in ('candidate_id','source_text','source_sha256')} for r in documents if r['supported']], 'oracle supported-document membership/order differs')
    require(len(sources)==len(mapping)==len(targets)==sum(len(r['clauses']) for r in docs.values())
            and len(plans)==len(docs) and len({r['id'] for r in targets})==len(targets),'oracle occurrence/document denominator differs')
    expected_targets=[];expected_map=[]
    for row in documents:
        if not row['supported']:continue
        a=labels[row['candidate_id']];coordinates=a.get('local_clause_coordinates',a.get('clause_coordinates'))
        require(len(coordinates)==len(row['clauses']),'oracle direct coordinate inventory differs')
        for ordinal,(clause,coordinate) in enumerate(zip(row['clauses'],coordinates,strict=True)):
            start,end=clause['char_start'],clause['char_end'];text=row['source_text'][start:end];h=text_sha(text)
            identity='oracle-'+digest([row['candidate_id'],ordinal,start,end,h]);local=local_row(row,{**coordinate,'rule':clause['rule']},end,identity)
            validate_coordinates(local);expected_targets.append(local)
            expected_map.append({'id':identity,'document_id':row['candidate_id'],'document_source_sha256':row['source_sha256'],
                'source_sha256':h,'char_start':start,'char_end':end,'occurrence_index':ordinal})
    require(targets==expected_targets and mapping==expected_map and sources==[{k:r[k] for k in ('id','source_text')} for r in targets], 'oracle target/substrings/relative roles/occurrence map differ')
    for row,plan in zip((r for r in documents if r['supported']),plans,strict=True):
        require(plan['candidate_id']==row['candidate_id'] and plan['source_sha256']==row['source_sha256']
                and plan['status']=='planned' and plan['source_plan']['source']=={k:row[k] for k in ('candidate_id','source_text','source_sha256')},'oracle plan source membership differs')
        chosen=[r for r in mapping if r['document_id']==row['candidate_id']];clauses=plan['source_plan']['clauses']
        require(len(clauses)==len(chosen) and all((v['clause_id'],v['char_start'],v['char_end'],v['source_text'],v['source_sha256'])==
            (m['id'],m['char_start'],m['char_end'],row['source_text'][m['char_start']:m['char_end']],m['source_sha256']) for v,m in zip(clauses,chosen,strict=True)), 'oracle plan occurrence intervals differ')
    return {'documents':len(docs),'occurrences':len(targets),'unique_source_substrings':len({r['source_text'] for r in targets}),
            'repeated_occurrences_retained':len(targets)-len({r['source_text'] for r in targets}),
            'scope_eligibility_supplied':True,'segmentation_supplied':True,'unsupported_denominator':0}


def audit_role_span_annotations(inputs,fresh_targets,fresh_pairs,fresh_document_targets,fresh_document_pairs,
    fresh_oracle_targets,ledger,exposure,*,historical_layout_pools,historical_source_inventory,fresh_oracle_inputs):
    """Pure independent audit; call only after replay and native build freezes."""
    m=inputs['manifest'];require(m['schema']=='authored-legal-role-span-rehearsal-corpus/v1'
        and len(inputs['legacy']['training'])==m['main_training_rows']==4080
        and digest(inputs['legacy']['training'])==m['main_training_sha256'],'unchanged separate main4080 binding differs')
    panels={'train':inputs['aux_rows'],'tuning':inputs['new_tuning'],'fresh':fresh_targets}
    pairs={'train':inputs['aux_pairs'],'tuning':inputs['tuning_pairs'],'fresh':fresh_pairs}
    require({p:len(v) for p,v in panels.items()}==SINGLE_COUNTS and len(ledger['single_rows'])==960
            and len(ledger['document_rows'])==192,'full960single192document annotation inventory required')
    annotations={a['id']:a for a in ledger['single_rows']};require(len(annotations)==960,'single annotation identities repeat')
    seen_sources=set();seen_meanings=set();seen_cases=set();single_counts={}
    for panel,rows in panels.items():
        require(Counter((r['canonical_ir']['rules'][0]['modality'],mask(r)) for r in rows)=={(modal,mask):len(rows)//24 for modal in 'OPF' for mask in range(8)},'single modality/mask cells unbalanced')
        require(Counter(annotations[r['id']]['family'] for r in rows)=={family:len(rows)//4 for family in FAMILIES},'four contrast family denominator differs')
        for row in rows:audit_single(row,annotations[row['id']],panel)
        cases=audit_pairs(rows,pairs[panel],annotations);sources={normalize(r['source_text']) for r in rows};meanings={digest(r['canonical_ir']) for r in rows}
        require(len(sources)==len(rows) and len(meanings)==len(rows)//2 and not sources&seen_sources
                and not meanings&seen_meanings and not cases&seen_cases,'single sources/cases/meanings cross splits')
        seen_sources|=sources;seen_meanings|=meanings;seen_cases|=cases
        single_counts[panel]={'rows':len(rows),'pairs':len(pairs[panel]),'headed':sum(bool(annotations[r['id']]['editorial_context']) for r in rows),
                             'condition_owned_timing_controls':sum(annotations[r['id']]['condition_owned_temporal_language'] for r in rows)}
    require(inputs['training_annotation_ledger']['single_rows']==[a for a in ledger['single_rows'] if a['panel']=='train']
            and inputs['tuning_annotation_ledger']['single_rows']==[a for a in ledger['single_rows'] if a['panel']=='tuning'],'admitted versus full annotation lineage differs')
    audit_blocks(panels['train'],pairs['train'],inputs['aux_blocks'],annotations)
    require([{k:r[k] for k in ('id','source_text')} for r in fresh_targets]==inputs['fresh_sources'],'fresh single target/source order differs')
    docs={'document_tuning':inputs['document_tuning'],'document_fresh':fresh_document_targets};doc_pairs={'document_tuning':inputs['document_tuning_pairs'],'document_fresh':fresh_document_pairs}
    oracle_targets={'document_tuning':inputs['oracle_targets']['new'],'document_fresh':fresh_oracle_targets}
    oracle_packs={'document_tuning':{k:inputs['oracle_'+k]['new'] for k in ('sources','occurrences','boundaries','document_sources')},'document_fresh':fresh_oracle_inputs}
    oracle_audit={}
    for panel,rows in docs.items():
        labels=[a for a in ledger['document_rows'] if a['panel']==panel];cases,local=audit_documents(rows,doc_pairs[panel],labels,panel)
        sources={normalize(r['source_text']) for r in rows+local};meanings={digest(r['canonical_ir']) for r in local}
        require(not sources&seen_sources and not meanings&seen_meanings and not cases&seen_cases,'document source/meaning/case overlaps a different split')
        seen_sources|=sources;seen_meanings|=meanings;seen_cases|=cases
        oracle_audit[panel]=audit_oracle_targets(rows,labels,oracle_targets[panel],oracle_packs[panel])
    require([{k:r[k] for k in ('candidate_id','source_text','source_sha256')} for r in fresh_document_targets]==inputs['fresh_document_sources'],'fresh document source/target inventory differs')
    require(inputs['tuning_annotation_ledger']['document_rows']==[a for a in ledger['document_rows'] if a['panel']=='document_tuning'],'tuning document annotation lineage differs')
    old_sources={normalize(s) for s in historical_source_inventory}
    require(not seen_sources&old_sources and exposure['new_source_overlap']==0,'new authored sources overlap audited history')
    require(exposure['prior_source_hashes_sha256']==digest(sorted(text_sha(s) for s in old_sources)),'historical source inventory hash differs')
    pools={**historical_layout_pools,'new_auxiliary':panels['train'],'new_tuning':panels['tuning'],
           'new_document_tuning':oracle_targets['document_tuning']}
    layouts={p:{independent_layout(r) for r in rows} for p,rows in pools.items()}
    require(exposure['known_pool_counts']=={p:len(v) for p,v in pools.items()}
            and exposure['known_role_masked_layouts']=={p:sorted(v) for p,v in layouts.items()},'independent known layout inventory differs')
    evidence=[]
    for panel,rows in (('single',fresh_targets),('oracle_document',fresh_oracle_targets)):
        for row in rows:
            layout=independent_layout(row);matches=sorted(p for p,values in layouts.items() if layout in values)
            evidence.append({'id':row['id'],'panel':panel,'source_sha256':text_sha(row['source_text']),'role_masked_layout':layout,
                'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination',
                'matched_new_auxiliary':'new_auxiliary' in matches})
    require(exposure['rows']==evidence and exposure['all_layouts_novel_claimed'] is False,'fresh exposure evidence or novelty claim differs')
    require(exposure['split_audit']==m['split_audit'] and len(seen_cases)==576,'declared case/split inventory differs')
    return {'schema':'legal-role-span-independent-annotation-audit/v1','main_training_rows':4080,'auxiliary_rows':576,
        'auxiliary_pairs':288,'complement_blocks':144,'two_present_two_absent_each_optional_field':True,
        'single_panels':single_counts,'oracle_panels':oracle_audit,'new_cases':len(seen_cases),'historical_layout_pools':len(historical_layout_pools),
        'fresh_layouts':{p:dict(Counter(r['layout_status'] for r in evidence if r['panel']==p)) for p in ('single','oracle_document')},
        'fresh_matching_auxiliary':{p:sum(r['matched_new_auxiliary'] for r in evidence if r['panel']==p) for p in ('single','oracle_document')},
        'cross_split_source_overlap':0,'historical_source_overlap':0,'semantic_gold_verified':False,
        'claim':'Author-stipulated flat examples; source/role/occurrence integrity and local exposure only. Supplied oracle segmentation and scope eligibility are not learned.'}
