"""Pure post-release audit of condition/deadline ownership and reused auxiliary.

No file access or model calls. Old576 rows/pairs/blocks remain an exact prefix;
the new192 have direct source coordinates. Receipt-time applicability atoms are
opaque conditions, not demonstrated support for nested temporal logic.
"""
from collections import Counter
from copy import deepcopy
import re
from scripts.ops.legal_ir import summarize_legal_role_span_rehearsal_annotations as previous

require,digest,text_sha,normalize,independent_layout=(getattr(previous,k) for k in
    ('require','digest','text_sha','normalize','independent_layout'))
FIELDS=previous.FIELDS
FAMILIES=('front_to_actor_infix','front_to_modal_infix','actor_infix_to_trailing','modal_infix_to_front')
CLASSES=('neither','condition_only','deadline_only','both')


def timing_roles(row,annotation):
    previous.validate_coordinates(row);rule=row['canonical_ir']['rules'][0];source=row['source_text']
    expected=[];kind=None
    if rule['conditions']:
        atom=rule['conditions'][0];matches=list(re.finditer(r' application was received (within \d+ (?:days|hours) of publication|before \d{4}-\d{2}-\d{2})$',atom))
        require(len(matches)==1,'condition must own an explicit complete receipt-timing predicate')
        suffix=matches[0].group(1);span=row['facet_spans']['conditions']
        expected.append({'owner':'conditions','char_start':span[0]+matches[0].start(1),'char_end':span[1],
                         'source_text':suffix,'relation':'opaque_receipt_timing_applicability_atom'})
    if rule['temporal']:
        literal=rule['temporal'][0];span=row['facet_spans']['temporal']
        kind='days' if re.fullmatch(r'within \d+ days',literal) else 'hours' if re.fullmatch(r'within \d+ hours',literal) else 'calendar' if re.fullmatch(r'before \d{4}-\d{2}-\d{2}',literal) else None
        require(kind is not None,'unsupported action deadline literal')
        expected.append({'owner':'temporal','char_start':span[0],'char_end':span[1],'source_text':literal,'relation':'independent_action_deadline'})
    ownership='both' if rule['conditions'] and rule['temporal'] else 'condition_only' if rule['conditions'] else 'deadline_only' if rule['temporal'] else 'neither'
    require(annotation['timing_role_spans']==sorted(expected,key=lambda p:p['char_start'])
            and annotation['timing_ownership']==ownership and annotation['condition_owned_temporal_language'] is bool(rule['conditions'])
            and annotation['temporal_kind']==kind,'timing owner, interval, origin or absence declaration differs')
    for item in expected:
        span=row['facet_spans'][item['owner']]
        require(span[0]<=item['char_start']<item['char_end']<=span[1] and source[item['char_start']:item['char_end']]==item['source_text'],
                'timing text escapes its exact owning source atom')
    if ownership=='both':require(rule['temporal'][0] not in rule['conditions'][0],'both timing literals must ground uniquely to separate atoms')
    return ownership


def expected_order(family,side):
    C,E,T='conditions','exceptions','temporal'
    order={FAMILIES[0]:((C,T,'actor',E,'trigger','action','object'),(T,'heading','actor',C,'trigger','action','object',E)),
        FAMILIES[1]:(('heading',E,C,T,'actor','trigger','action','object'),('heading','actor',E,'trigger',C,T,'action','object')),
        FAMILIES[2]:(('heading','actor',C,T,'trigger',E,'action','object'),('heading','actor','trigger','action','object',E,T,C)),
        FAMILIES[3]:(('heading','actor',E,'trigger',T,C,'action','object'),(T,C,E,'heading','actor','trigger','action','object'))}
    return order[family][side]


def audit_single(row,a,panel):
    intervals=previous.validate_coordinates(row);ownership=timing_roles(row,a);text=row['source_text']
    require(row['id']=='timing-'+text_sha(text) and a['id']==row['id'] and a['source_sha256']==text_sha(text)
            and a['panel']==panel and a['family'] in FAMILIES and a['side'] in (0,1),'timing source/annotation identity differs')
    require(a['facet_spans']==row['facet_spans'] and a['trigger_span']==row['trigger_span'] and a['presence_mask']==previous.mask(row)
            and a['annotation_authority']==previous.AUTHORITY,'direct role/trigger annotation differs')
    layout=independent_layout(row);require(a['role_masked_layout']==layout and a['layout_sha256']==text_sha(layout),'role layout fingerprint differs')
    notes=previous.captions_in_source(row);require(a['editorial_context']==notes and len(notes)==(0 if a['family']==FAMILIES[0] and a['side']==0 else 1),'caption presence differs')
    require(a['caption_style'] in range(3) and all(n['source_text']==previous.CAPTIONS[a['caption_style']] for n in notes),'source caption style differs')
    for n in notes:require(all(end<=n['start_char'] or start>=n['end_char'] for start,end,_ in intervals),'caption overlaps semantic atom')
    positions={f:span[0] for f,span in row['facet_spans'].items() if span is not None};positions['trigger']=row['trigger_span'][0]
    if notes:positions['heading']=notes[0]['start_char']
    require(tuple(sorted(positions,key=positions.get))==tuple(k for k in expected_order(a['family'],a['side']) if k in positions),'realized timing placement differs')
    cues=[]
    for field,values in (('conditions',('if','when','provided that')),('exceptions',('unless','except when','except where'))):
        span=row['facet_spans'][field]
        if span:
            found=[cue+' ' for cue in values if text[:span[0]].endswith(cue+' ')];require(len(found)==1,'one source-bound qualifier cue required')
            cue=found[0];cues.append({'field':field,'start_char':span[0]-len(cue),'end_char':span[0],'source_text':cue})
    require(a['qualifier_cues']==sorted(cues,key=lambda p:p['start_char']),'qualifier cue annotation differs')
    return ownership


def audit_blocks(rows,pairs,blocks,count):
    lookup={r['id']:r for r in rows};pm={p['pair_id']:p for p in pairs};seen=[]
    require(len(rows)==count*4 and len(pairs)==count*2 and len(blocks)==count,'combined/new block denominator differs')
    for b in blocks:
        require(set(b)=={'block_id','pair_ids'} and len(b['pair_ids'])==len(set(b['pair_ids']))==2 and set(b['pair_ids'])<=set(pm)
                and b['block_id']=='block-'+digest(b['pair_ids']),'closed source-independent complementary pair block required')
        selected=[lookup[pm[p][side]] for p in b['pair_ids'] for side in ('left_id','right_id')]
        require(len({r['id'] for r in selected})==4 and previous.mask(selected[0])^previous.mask(selected[2])==7
                and all(sum(bool(r['canonical_ir']['rules'][0][f]) for r in selected)==2 for f in FIELDS[3:]),'complement mask balance differs')
        require(len({r['canonical_ir']['rules'][0]['modality'] for r in selected})==1,'block modality differs')
        for p in b['pair_ids']:
            left,right=lookup[pm[p]['left_id']],lookup[pm[p]['right_id']]
            require(left['canonical_ir']==right['canonical_ir'] and digest(left['canonical_ir'])==pm[p]['canonical_ir_sha256'],'paired canonical meaning differs')
        seen.extend(b['pair_ids'])
    require(len(seen)==len(set(seen))==len(pairs),'pairs reused across blocks')


def audit_document_roles(documents,annotations):
    rows={r['candidate_id']:r for r in documents};counts=Counter()
    for a in annotations:
        row=rows[a['candidate_id']]
        for index,c in enumerate(a['local_clause_coordinates']):
            start,end=c['char_start'],c['char_end'];local=previous.local_row(row,c,end,'oracle-validation')
            label={**c,'timing_role_spans':[{**v,'char_start':v['char_start']-start,'char_end':v['char_end']-start} for v in c['timing_role_spans']]}
            ownership=timing_roles(local,label)
            if row['supported']:counts[ownership]+=1
    return dict(counts)


def audit_timing_annotations(inputs,fresh_targets,fresh_pairs,fresh_document_targets,fresh_document_pairs,
    fresh_oracle_targets,ledger,exposure,*,historical_layout_pools,historical_source_inventory,fresh_oracle_inputs):
    old=inputs['prior_role_inputs'];m=inputs['manifest']
    require(m['schema']=='authored-legal-timing-ownership-corpus/v1' and len(inputs['legacy']['training'])==4080
            and inputs['legacy']['training']==old['legacy']['training'] and digest(inputs['legacy']['training'])==m['main_training_sha256'],'main4080 changed')
    require(inputs['aux_rows']==old['aux_rows']+inputs['ownership_rows'] and inputs['aux_pairs']==old['aux_pairs']+inputs['ownership_pairs']
            and inputs['aux_blocks']==old['aux_blocks']+inputs['ownership_blocks'] and len(old['aux_rows'])==576,'frozen576 auxiliary prefix changed')
    require(m['retained_auxiliary_refs']=={k:old['manifest']['artifacts'][k] for k in ('aux_rows','aux_pairs','aux_blocks')},'old auxiliary reference binding differs')
    audit_blocks(inputs['aux_rows'],inputs['aux_pairs'],inputs['aux_blocks'],192)
    audit_blocks(inputs['ownership_rows'],inputs['ownership_pairs'],inputs['ownership_blocks'],48)
    require(len(ledger['single_rows'])==576 and len(ledger['document_rows'])==192,'all newly authored annotations required')
    annotations={a['id']:a for a in ledger['single_rows']};require(len(annotations)==576,'duplicate annotation identity')
    panels={'train':inputs['ownership_rows'],'tuning':inputs['new_tuning'],'fresh':fresh_targets}
    pairs={'train':inputs['ownership_pairs'],'tuning':inputs['tuning_pairs'],'fresh':fresh_pairs}
    seen_sources=set();seen_meanings=set();seen_cases=set();summaries={}
    for panel,rows in panels.items():
        require(len(rows)==192 and Counter((r['canonical_ir']['rules'][0]['modality'],previous.mask(r)) for r in rows)=={(m,k):8 for m in 'OPF' for k in range(8)},'balanced modality/mask grid differs')
        counts=Counter(audit_single(r,annotations[r['id']],panel) for r in rows)
        require(counts=={k:48 for k in CLASSES} and Counter(annotations[r['id']]['caption_style'] for r in rows)=={k:64 for k in range(3)}
                and Counter(annotations[r['id']]['family'] for r in rows)=={k:48 for k in FAMILIES},'timing ownership/caption/family cells differ')
        cases=previous.audit_pairs(rows,pairs[panel],annotations);sources={normalize(r['source_text']) for r in rows};meanings={digest(r['canonical_ir']) for r in rows}
        require(len(sources)==192 and len(meanings)==96 and not(sources&seen_sources or meanings&seen_meanings or cases&seen_cases),'new single source/case/meaning overlap')
        seen_sources|=sources;seen_meanings|=meanings;seen_cases|=cases;summaries[panel]={'rows':192,'pairs':96,'ownership_classes':dict(counts)}
    require(inputs['ownership_training_annotation_ledger']['single_rows']==[a for a in ledger['single_rows'] if a['panel']=='train']
            and inputs['training_annotation_ledger']['single_rows']==old['training_annotation_ledger']['single_rows']+inputs['ownership_training_annotation_ledger']['single_rows']
            and inputs['tuning_annotation_ledger']['single_rows']==[a for a in ledger['single_rows'] if a['panel']=='tuning'],'admitted new/combined ledger lineage differs')
    require([{k:r[k] for k in ('id','source_text')} for r in fresh_targets]==inputs['fresh_sources'],'fresh single source join differs')
    docs={'document_tuning':inputs['document_tuning'],'document_fresh':fresh_document_targets};dpairs={'document_tuning':inputs['document_tuning_pairs'],'document_fresh':fresh_document_pairs}
    targets={'document_tuning':inputs['oracle_targets']['new'],'document_fresh':fresh_oracle_targets};packs={'document_tuning':{k:inputs['oracle_'+k]['new'] for k in ('sources','occurrences','boundaries','document_sources')},'document_fresh':fresh_oracle_inputs}
    docaudit={}
    for panel,rows in docs.items():
        labels=[a for a in ledger['document_rows'] if a['panel']==panel];cases,local=previous.audit_documents(rows,dpairs[panel],labels,panel)
        ownership=audit_document_roles(rows,labels);sources={normalize(r['source_text']) for r in rows+local};meanings={digest(r['canonical_ir']) for r in local}
        require(not(sources&seen_sources or meanings&seen_meanings or cases&seen_cases),'document cases/sources/meanings cross authored splits')
        seen_sources|=sources;seen_meanings|=meanings;seen_cases|=cases
        docaudit[panel]={**previous.audit_oracle_targets(rows,labels,targets[panel],packs[panel]),'supported_occurrence_ownership':ownership}
    require([{k:r[k] for k in ('candidate_id','source_text','source_sha256')} for r in fresh_document_targets]==inputs['fresh_document_sources'],'fresh full document/source join differs')
    require(inputs['tuning_annotation_ledger']['document_rows']==[a for a in ledger['document_rows'] if a['panel']=='document_tuning'],'admitted document ledger differs')
    old_sources={normalize(s) for s in historical_source_inventory}
    require(not seen_sources&old_sources and exposure['new_source_overlap']==0 and exposure['prior_source_hashes_sha256']==digest(sorted(text_sha(s) for s in old_sources)),
            'new sources overlap history or historical source digest differs')
    pools={**historical_layout_pools,'new_ownership_train':inputs['ownership_rows'],'new_ownership_tuning':inputs['new_tuning'],
           'new_ownership_document_tuning':inputs['oracle_targets']['new']}
    layouts={k:{independent_layout(r) for r in rows} for k,rows in pools.items()}
    require(exposure['known_pool_counts']=={k:len(v) for k,v in pools.items()} and exposure['known_role_masked_layouts']=={k:sorted(v) for k,v in layouts.items()},'independent historical/current layout inventory differs')
    evidence=[]
    for panel,rows in (('single',fresh_targets),('oracle_document',fresh_oracle_targets)):
        for row in rows:
            layout=independent_layout(row);matches=sorted(k for k,values in layouts.items() if layout in values)
            evidence.append({'id':row['id'],'panel':panel,'source_sha256':text_sha(row['source_text']),'role_masked_layout':layout,
                'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination',
                'matched_new_ownership_training':'new_ownership_train' in matches})
    require(exposure['rows']==evidence and exposure['structural_novelty_claimed'] is False and m['split_audit']==exposure['split_audit']
            and len(seen_cases)==384,'exposure rows/declared shared structure/case inventory differ')
    return {'schema':'legal-timing-ownership-independent-annotation-audit/v1','main_training_rows':4080,'retained_auxiliary_rows':576,
        'new_auxiliary_rows':192,'combined_auxiliary_rows':768,'combined_pairs':384,'combined_blocks':192,
        'new_blocks':48,'new_single_panels':summaries,'new_document_panels':docaudit,
        'historical_layout_pools':len(historical_layout_pools),'new_case_groups':len(seen_cases),
        'fresh_layouts':{p:dict(Counter(r['layout_status'] for r in evidence if r['panel']==p)) for p in ('single','oracle_document')},
        'new_source_history_overlap':0,'structural_novelty_claimed':False,'statutory_gold_verified':False,
        'condition_timing_is_opaque_applicability_atom':True,'supplied_oracle_segmentation_and_support_membership':True}
