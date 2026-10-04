"""Pure independent post-release atom/endpoint annotation and exposure audit.

No file opens, model calls or production decisions. All source/meaning labels
are authored flat-profile controls; compilation is not legal fidelity.
"""
from collections import Counter
from copy import deepcopy
import random
import re
from scripts.ops.legal_ir import summarize_legal_heading_boundary_annotations as heading
adapter=heading.adapter
boundary,require,normalize=heading.boundary,heading.require,heading.normalize
FIELDS=adapter.previous.FIELDS
SOURCE_KEYS={'candidate_id','source_text','source_sha256'}
COUNTS={'train':144,'tuning':96,'fresh':192}
FACTORS={'front_class','preceding_time_kind','first_modality','clause_count','variant','child_structure'}
STRUCTURES={'train':'time_heading_qualifiers_actor','tuning':'heading_time_qualifiers_actor','fresh':'qualifiers_time_heading_actor'}
ATOM_FIELDS=('actor','temporal','exceptions')
ATOM_ROLE_KEYS={'candidate_id','source_sha256','inter_clause_end_token_indices','atom_interior_negative_token_indices','atom_spans','provenance'}
PAIR_KEYS={'pair_id','forward_id','rotated_id','local_clause_body_sha256'}
HEADINGS=('(2) Filing duty: ','Record duty [2]. ')


def audit_document(row,annotation,panel):
    require(set(annotation)==adapter.previous.ANNOTATION_KEYS|{'factors','body_order'},'closed atom source annotation required')
    f=annotation['factors'];order=annotation['body_order']
    require(set(f)==FACTORS and f['child_structure']==STRUCTURES[panel] and annotation['family']==STRUCTURES[panel],
        'split-specific actual child role order required')
    require(type(f['variant']) is int and 0<=f['variant']<(2 if panel=='tuning' else 4),'declared variant range differs')
    require(row['candidate_id']=='scope-'+adapter.text_sha(row['source_text']) and
        row['construction']==(annotation['family'] if row['supported'] else 'unsupported/nested_normative_exception'),
        'opaque source identity or construction differs')
    clone={k:deepcopy(v) for k,v in annotation.items() if k not in ('factors','body_order')};clone['family']='numbered_child'
    layout=adapter.previous.audit_document({**row,'construction':'numbered_child' if row['supported'] else row['construction']},clone,panel)
    local=annotation['local_clause_coordinates'];count=len(local)
    require(count==f['clause_count'] in (2,3) and type(order) is list and all(type(v) is int for v in order)
        and sorted(order)==list(range(count)),'exact local body permutation differs')
    if panel!='train':require(order==list(range(count)),'evaluation body order must remain canonical')
    first=local[order.index(0)];child=local[order.index(1)]
    require(first['rule']['modality']==f['first_modality'] in 'OPF','canonical first-body modality differs')
    kind=f['preceding_time_kind'];time=first['rule']['temporal']
    if kind=='none':require(time==[],'absent preceding temporal factor differs')
    else:
        patterns={'days':r'within \d+ days','hours':r'within \d+ hours','calendar':r'before \d{4}-\d{2}-\d{2}'}
        require(kind in patterns and len(time)==1 and re.fullmatch(patterns[kind],time[0]),'preceding time kind differs')
    present=[k for k in ('conditions','exceptions') if child['rule'][k]]
    require(f['front_class'] in ('C','E','CE') and present=={'C':['conditions'],'E':['exceptions'],'CE':['conditions','exceptions']}[f['front_class']],
        'fronted qualifier presence factor differs')
    spans=child['facet_spans'];notes=child['editorial_context']
    require(len(notes)==1 and notes[0]['source_text'] in HEADINGS and spans['temporal'] is not None,'source-bound child heading/time required')
    positions={'time':spans['temporal'],'heading':[notes[0]['start_char'],notes[0]['end_char']],
        'qualifiers':[min(spans[k][0] for k in present),max(spans[k][1] for k in present)],'actor':spans['actor']}
    ordered=sorted(positions.values(),key=lambda span:span[0])
    require(all(a[1]<=b[0] for a,b in zip(ordered,ordered[1:])),'compound qualifier/heading/time blocks overlap')
    require('_'.join(sorted(positions,key=lambda k:positions[k][0]))==STRUCTURES[panel],
        'realized heading/qualifier/time role order differs')
    require(all(o is child or not o['editorial_context'] for o in local),'unexpected extra editorial ownership')
    require(len(boundary.tokenize(row['source_text']))<=512 and not boundary.UNSUPPORTED.search(row['source_text']),
        'complete bounded unchanged-flat-profile source required')
    return layout


def audit_rotation_pairs(rows,pairs,annotations):
    require(len(rows)==144 and len(pairs)==72,'exact72 training contrasts required')
    lookup={r['candidate_id']:r for r in rows};seen=set();cases=set()
    require(len(lookup)==144 and all(r['supported'] for r in rows),'all144 unique supported TRAIN required')
    for pair in pairs:
        require(set(pair)==PAIR_KEYS,'closed rotation pair required')
        ids=(pair['forward_id'],pair['rotated_id'])
        require(ids[0]!=ids[1] and all(i in lookup and i not in seen for i in ids),'unique rotation membership required')
        left,right=(annotations[i] for i in ids);body=left['local_clause_coordinates'];rotated=right['local_clause_coordinates']
        require(left['case_group']==right['case_group'] and left['case_group'] not in cases and left['factors']==right['factors']
            and pair['pair_id']=='pair-'+adapter.text_sha(left['case_group']),'rotation case/factor binding differs')
        require(left['body_order']==list(range(len(body))) and right['body_order']==[len(body)-1]+list(range(len(body)-1)),
            'declared last-body-first rotation differs')
        require([o['source_sha256'] for o in body]==pair['local_clause_body_sha256']
            and [o['source_text'] for o in rotated]==[o['source_text'] for o in body][-1:]+[o['source_text'] for o in body][:-1]
            and [o['rule'] for o in rotated]==[o['rule'] for o in body][-1:]+[o['rule'] for o in body][:-1],
            'source order contrast changed exact local bodies or meaning')
        seen.update(ids);cases.add(left['case_group'])
    require(seen==set(lookup),'exhaustive rotation pair membership required')
    return {'documents':144,'pairs':72,'cases':sorted(cases),'all_supported':True,'exact_local_body_and_meaning_rotation':True}


def audit_atom_roles(rows,records,annotations):
    require(len(rows)==len(records)==864 and all(r['supported'] for r in rows),'only864 supported TRAIN atom masks required')
    total_positive=total_negative=0;kind_counts=Counter()
    for row,record in zip(rows,records,strict=True):
        require(set(record)==ATOM_ROLE_KEYS and record['candidate_id']==row['candidate_id']
            and record['source_sha256']==row['source_sha256'] and record['provenance']=='pinned_supported_train_atoms_and_inter_clause_endpoints/v1',
            'closed source-bound atom record differs')
        source=row['source_text'];tokens=boundary.tokenize(source);ends={c['char_end'] for c in row['clauses']}
        require(ends and max(ends)==len(source.rstrip()) and ends<={t['char_end'] for t in tokens},'complete token-aligned gold ends required')
        expected=[]
        for clause in row['clauses']:
            text=source[clause['char_start']:clause['char_end']]
            for field in ATOM_FIELDS:
                values=clause['rule'][field];values=[values] if type(values) is str else values
                require(type(values) is list and len(values)<=1,'bounded single copied atom required')
                for value in values:
                    found=list(re.finditer(re.escape(value),text));require(len(found)==1,'canonical atom grounding must be unique in its own occurrence')
                    start=clause['char_start']+found[0].start();expected.append({'kind':field,'char_start':start,'char_end':start+len(value)})
        expected.sort(key=lambda s:(s['char_start'],s['char_end'],s['kind']))
        require(all(a['char_end']<=b['char_start'] for a,b in zip(expected,expected[1:])),'canonical copied role spans overlap')
        require(record['atom_spans']==expected,'atom role interval differs from canonical source provenance')
        if row['candidate_id'] in annotations:
            direct=sorted(({'kind':k,'char_start':o['facet_spans'][k][0],'char_end':o['facet_spans'][k][1]}
                for o in annotations[row['candidate_id']]['local_clause_coordinates'] for k in ATOM_FIELDS if o['facet_spans'][k]),
                key=lambda s:(s['char_start'],s['char_end'],s['kind']))
            require(direct==expected,'authored direct TRAIN atom spans disagree with canonical grounding')
        positives=[i for i,t in enumerate(tokens) if t['char_end'] in ends-{max(ends)}]
        negatives=[i for i,t in enumerate(tokens) if t['char_end'] not in ends and
            any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in expected)]
        require(record['inter_clause_end_token_indices']==positives and record['atom_interior_negative_token_indices']==negatives,
            'complete inter-clause endpoint or all-atom-token negative indices differ')
        total_positive+=len(positives);total_negative+=len(negatives);kind_counts.update(s['kind'] for s in expected)
    require((total_positive,total_negative)==(1320,18284) and kind_counts=={'actor':2184,'exceptions':1176,'temporal':1026},
        'fixed TRAIN atom-role denominator differs')
    return {'documents':864,'inter_clause_end_tokens':total_positive,'atom_interior_negative_tokens':total_negative,
        'span_counts':dict(kind_counts),'unsupported_training_rows_excluded':432,'prediction_based_masks':False,
        'terminal_end_tokens_excluded_from_inter_clause_positive_mask':864}


def audit_training_roles(inputs,prior_annotation_ledgers,train_annotations):
    historical={**inputs,'boundary_training':inputs['boundary_training'][:720],'training_token_roles':inputs['training_token_roles'][:720]}
    old=heading.audit_training_token_roles(historical,prior_annotation_ledgers)
    require(inputs['boundary_training']==historical['boundary_training']+inputs['atom_train']
        and len(inputs['training_token_roles'])==864,'full864 supported-only order required')
    count_positive=count_negative=0
    for row,record in zip(inputs['atom_train'],inputs['training_token_roles'][720:],strict=True):
        require(set(record)==heading.ROLE_KEYS and record['candidate_id']==row['candidate_id'] and record['source_sha256']==row['source_sha256']
            and record['provenance']=='pinned_train_endpoints_and_optional_editorial_spans/v1','new supported TRAIN heading record differs')
        a=train_annotations[row['candidate_id']];source=row['source_text'];tokens=boundary.tokenize(source)
        notes=sorted(({'char_start':n['start_char'],'char_end':n['end_char']} for o in a['local_clause_coordinates'] for n in o['editorial_context']),
            key=lambda n:(n['char_start'],n['char_end']))
        ends={c['char_end'] for c in row['clauses']};positives=[i for i,t in enumerate(tokens) if t['char_end'] in ends]
        negatives=[i for i,t in enumerate(tokens) if re.fullmatch(r'[^\w\s]',t['text']) and i not in positives
            and any(n['char_start']<=t['char_start']<t['char_end']<=n['char_end'] for n in notes)]
        require(record['editorial_heading_spans']==notes and record['true_end_token_indices']==positives
            and record['editorial_hard_negative_token_indices']==negatives,'new direct TRAIN editorial/endpoint roles differ')
        count_positive+=len(positives);count_negative+=len(negatives)
    all_annotations={a['candidate_id']:a for bundle in prior_annotation_ledgers.values() for a in bundle['ledger']['document_rows']}
    all_annotations.update(train_annotations)
    atom=audit_atom_roles(inputs['boundary_training'],inputs['training_atom_roles'],all_annotations)
    require(inputs['manifest']['training_atom_role_counts']=={k:atom[k] for k in ('documents','inter_clause_end_tokens','atom_interior_negative_tokens','span_counts')},
        'manifest atom role coverage differs')
    return {'historical_heading_masks':old,'new_true_end_tokens':count_positive,'new_editorial_negative_tokens':count_negative,'atom_masks':atom}


def audit_atom_annotations(inputs,fresh_targets,fresh_pairs,ledger,exposure,*,historical_documents,
    prior_annotation_ledgers,historical_source_inventory,historical_manifests,prior_training_pairs):
    from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs
    names={'prior_scope','prior_condition','prior_adapter','prior_adapter_config','prior_preservation','prior_heading'}
    require(set(historical_manifests)==names,'six pinned historical manifest/config values required')
    old_scope,old_condition,old_adapter,old_config,old_preservation,old_heading=(historical_manifests[k] for k in
        ('prior_scope','prior_condition','prior_adapter','prior_adapter_config','prior_preservation','prior_heading'))
    m=inputs['manifest'];require(m['schema']=='authored-legal-atom-boundary-corpus/v1'
        and m['historical_training_reused_without_changes'] is True and m['training_documents']==1296
        and m['historical_training_documents']==1152 and m['supervised_training_documents']==864 and m['new_training_documents']==144,
        'exact unchanged history plus144supported training declaration required')
    require(old_config['scope_corpus_manifest']==old_preservation['inputs']['prior_adapter_corpus'],'adapter config ancestry differs')
    expected_retention={**old_heading['retention_target_references'],'prior_heading_tuning':old_heading['artifacts']['tuning_targets'],
        'prior_heading_fresh':old_heading['artifacts']['fresh_targets']}
    require(m['retention_target_references']==expected_retention and len(expected_retention)==21,'all21 historical panels required')
    require(m['replay_references']==old_adapter['replay_references'] and all(m['artifacts'][k]==old_adapter['artifacts'][k]
        for k in ('new_training_targets','training_pairs','training_sources')),'old TRAIN references changed')
    expected_refs={**old_scope['replay_references'],'prior_scope':old_scope['artifacts']['new_training_targets'],
        **old_scope['retention_target_references'],'prior_scope_tuning':old_scope['artifacts']['tuning_targets'],
        'prior_scope_exposed_fresh':old_scope['artifacts']['fresh_targets'],'condition_document_tuning':old_condition['artifacts']['document_tuning_targets'],
        'condition_exposed_documents':old_condition['artifacts']['document_challenge_targets'],
        'prior_adapter_train':old_adapter['artifacts']['new_training_targets'],'prior_adapter_tuning':old_adapter['artifacts']['tuning_targets'],
        'prior_adapter_fresh':old_adapter['artifacts']['fresh_targets'],'prior_preservation_tuning':old_preservation['artifacts']['tuning_targets'],
        'prior_preservation_fresh':old_preservation['artifacts']['fresh_targets'],'prior_heading_tuning':old_heading['artifacts']['tuning_targets'],
        'prior_heading_fresh':old_heading['artifacts']['fresh_targets']}
    require(set(historical_documents)==set(expected_refs) and all(historical_documents[k]['reference']==v for k,v in expected_refs.items()),
        'complete pinned historical document inventory required')
    require(inputs['new_train']==historical_documents['prior_adapter_train']['rows'] and len(inputs['new_train'])==384
        and prior_training_pairs['reference']==old_adapter['artifacts']['training_pairs'] and inputs['training_pairs']==prior_training_pairs['rows'],
        'exact reused384 training documents/192pairs required')
    require(set(inputs['replay'])==set(old_adapter['replay_references']) and all(rows==historical_documents[k]['rows'] for k,rows in inputs['replay'].items())
        and sum(map(len,inputs['replay'].values()))==768,'exact768 historical replay required')
    require(set(inputs['tuning'])==set(expected_retention)|{'atom_new'} and len(inputs['tuning'])==22
        and sum(map(len,inputs['tuning'].values()))==2448,'all22 admitted tuning panels/2448docs required')
    for name,pin in expected_retention.items():
        old=[v['rows'] for v in historical_documents.values() if v['reference']==pin]
        require(old and inputs['tuning'][name]==old[0],'historical tuning content/order differs:'+name)
    verify_scope_pairs(inputs['new_train'],inputs['training_pairs'],192)
    panels={'train':inputs['atom_train'],'tuning':inputs['tuning']['atom_new'],'fresh':fresh_targets}
    require({p:len(v) for p,v in panels.items()}==COUNTS,'complete432 new authored source documents required')
    trainledger=inputs['training_annotation_ledger']
    for value,n,allowed in ((trainledger,144,{'train'}),(ledger,288,{'tuning','fresh'})):
        require(set(value)=={'schema','document_rows'} and value['schema']=='legal-atom-boundary-annotations/v1'
            and len(value['document_rows'])==n and {a['panel'] for a in value['document_rows']}==allowed,
            'training and evaluation annotation ledgers must remain separated')
    annotations={a['candidate_id']:a for value in (trainledger,ledger) for a in value['document_rows']}
    require(len(annotations)==432 and set(annotations)=={r['candidate_id'] for rows in panels.values() for r in rows},'complete unique annotations required')
    require([{k:r[k] for k in SOURCE_KEYS} for r in fresh_targets]==inputs['sources']['atom_fresh']
        and all(set(r)==SOURCE_KEYS for r in inputs['sources']['atom_fresh']),'opaque source-only complete fresh join differs')
    layouts={};audits={};sources={};meanings={};cases={}
    for index,(panel,rows) in enumerate(panels.items()):
        labels=[annotations[r['candidate_id']] for r in rows]
        layouts[panel]={r['candidate_id']:audit_document(r,annotations[r['candidate_id']],panel) for r in rows}
        if panel=='train':audit=audit_rotation_pairs(rows,inputs['atom_training_pairs'],annotations)
        else:
            pairs=inputs['tuning_pairs'] if panel=='tuning' else fresh_pairs;audit=verify_scope_pairs(rows,pairs,len(rows)//2)
            for pair in pairs:
                a,b=(annotations[pair[k]] for k in ('independent_id','nested_id'))
                require(a['case_group']==b['case_group']==pair['case_group'] and a['factors']==b['factors'],'scope pair case/factor binding differs')
                require([o['source_text'] for o in a['local_clause_coordinates']]==[o['source_text'] for o in b['local_clause_coordinates']]
                    and [o['rule'] for o in a['local_clause_coordinates']]==[o['rule'] for o in b['local_clause_coordinates']],
                    'scope pair changes exact local source/meaning')
        for key,values in (('first_modality','OPF'),('front_class',('C','E','CE')),('preceding_time_kind',('none','days','hours','calendar')),('clause_count',(2,3))):
            for side in ((True,) if panel=='train' else (True,False)):
                subset=[a for a in labels if a['supported'] is side]
                require(Counter(str(a['factors'][key]) for a in subset)=={str(v):len(subset)//len(values) for v in values},
                    'realized per-class factor margin differs:'+key)
        crossed=('front_class','preceding_time_kind','first_modality','clause_count') if panel=='train' else ('front_class','preceding_time_kind','clause_count','variant')
        require(len({tuple(a['factors'][k] for k in crossed) for a in labels})==len(rows)//2,'complete declared factor combination grid required')
        literal={h:sum(h in r['source_text'] for r in rows) for h in HEADINGS}
        require(literal==dict.fromkeys(HEADINGS,len(rows)//2),'actual rendered heading balance differs')
        original=[a['candidate_id'] for a in (trainledger if panel=='train' else ledger)['document_rows'] if a['panel']==panel]
        random.Random(924173+index).shuffle(original)
        require(original==[r['candidate_id'] for r in rows],'opaque source order shuffle differs')
        sources[panel]={normalize(r['source_text']) for r in rows};meanings[panel]={boundary.digest(o['rule']) for a in labels for o in a['local_clause_coordinates']}
        cases[panel]=set(audit['cases']);require(len(sources[panel])==len(rows),'duplicate source in new panel')
        audits[panel]={**audit,'heading_literals':literal,'factor_counts':{k:dict(Counter(str(a['factors'][k]) for a in labels)) for k in sorted(FACTORS)},
            'local_occurrences':sum(len(a['local_clause_coordinates']) for a in labels)}
    for groups in (sources,meanings,cases):
        require(all(not groups[a]&groups[b] for a in groups for b in groups if a<b),'source/meaning/case split overlap')
    required_ledgers={'prior_scope':(old_scope,'legal-scope-retention-annotations/v1'),
        'prior_adapter':(old_adapter,'legal-scope-adapter-annotations/v1'),'prior_preservation':(old_preservation,'legal-scope-preservation-annotations/v1'),
        'prior_heading':(old_heading,'legal-heading-boundary-annotations/v1')}
    require(set(prior_annotation_ledgers)==set(required_ledgers),'four pinned historical annotation bundles required')
    old_annotations={}
    for name,(manifest,schema) in required_ledgers.items():
        bundle=prior_annotation_ledgers[name]
        require(bundle['reference']==manifest['artifacts']['annotation_ledger'] and bundle['ledger']['schema']==schema,'old annotation provenance differs')
        for a in bundle['ledger']['document_rows']:
            require(a['candidate_id'] not in old_annotations,'duplicate historical annotation identity');old_annotations[a['candidate_id']]=(name,a)
    history_layouts={};skipped={};old_source_from_docs=set();oldmeanings=set();oldcases=set()
    for name,bundle in historical_documents.items():
        history_layouts[name]=[];skipped[name]=[]
        for row in bundle['rows']:
            old_source_from_docs.add(normalize(row['source_text']));oldmeanings.update(boundary.digest(c['rule']) for c in row['clauses'])
            identity=row['candidate_id']
            if identity in old_annotations:
                origin,a=old_annotations[identity];oldcases.add(a['case_group'])
                if origin=='prior_heading':layout=heading.audit_document(row,a,a['panel'])
                elif origin=='prior_scope':layout=adapter.previous.audit_document(row,a,a['panel'])
                else:layout=adapter.audit_document(row,a,a['panel'])
            else:layout=adapter.historical_flat_layout(row)
            if layout is None:skipped[name].append(identity)
            else:history_layouts[name].append({'candidate_id':identity,'source_sha256':row['source_sha256'],'role_masked_layout':layout})
    known={k:sorted({r['role_masked_layout'] for r in v}) for k,v in history_layouts.items()}
    known.update({'new_'+p:sorted(set(layouts[p].values())) for p in ('train','tuning')})
    require(exposure['schema']=='legal-atom-boundary-exposure/v1' and exposure['historical_document_references']==expected_refs
        and exposure['historical_annotation_references']=={k:v['reference'] for k,v in prior_annotation_ledgers.items()}
        and exposure['historical_layout_rows']==history_layouts and exposure['historical_unannotated_unsupported_ids']==skipped
        and exposure['known_role_masked_layouts']==known and exposure['declared_child_structures']==STRUCTURES,
        'independent complete historical/new layout reconstruction differs')
    expected=[]
    for row in fresh_targets:
        identity=row['candidate_id'];layout=layouts['fresh'][identity];matches=sorted(k for k,v in known.items() if layout in v)
        require(not matches,'claimed fresh role layout already exposed')
        expected.append({'candidate_id':identity,'source_sha256':row['source_sha256'],'case_group':annotations[identity]['case_group'],
            'role_masked_layout':layout,'matching_pools':matches,'layout_status':'unmatched_audited_combination',
            'child_structure':STRUCTURES['fresh']})
    require(exposure['rows']==expected,'complete192 source-level exposure evidence differs')
    oldtexts={normalize(s) for s in historical_source_inventory['source_texts']}
    require(old_source_from_docs<=oldtexts and exposure['historical_source_inventory_count']==len(oldtexts)
        and exposure['historical_source_inventory_sha256']==boundary.digest(sorted(oldtexts)),'historical source commitment differs')
    require(exposure['prior_source_references']==historical_source_inventory['prior_source_references']
        and exposure['prior_condition_single_references']==historical_source_inventory['condition_single_references']
        =={k:old_condition['artifacts'][k] for k in ('new_tuning','challenge_targets')}
        and exposure['real_exposed_views']==historical_source_inventory['real_exposed_views']==86,'full earlier source ancestry differs')
    require(not oldtexts&set.union(*sources.values()) and not oldmeanings&set.union(*meanings.values())
        and not oldcases&set.union(*cases.values()) and exposure['new_source_overlap_count']==0,'new corpus overlaps historical source/meaning/case')
    training=audit_training_roles(inputs,prior_annotation_ledgers,{a['candidate_id']:a for a in trainledger['document_rows']})
    return {'schema':'legal-atom-boundary-independent-annotation-audit/v1','panels':audits,'training_roles':training,
        'unchanged_historical_training_documents':1152,'new_supported_training_documents':144,'new_training_rotation_pairs':72,
        'new_evaluation_documents':288,'new_scope_pairs':144,'source_and_declared_structural_split_verified':True,
        'fresh_layout_counts':dict(Counter(r['layout_status'] for r in expected)),
        'historical_unsupported_without_role_annotations':{k:len(v) for k,v in skipped.items()},
        'source_hash_ids_have_no_explicit_class_fields':True,'class_neutral_source_order_shuffle_verified':True,
        'historical_source_and_supported_meaning_overlap':0,'helper_opens_files':False,'statutory_gold_available':False,
        'limits':['Individual cue words, atom grammar and heading punctuation remain shared; the declared role-order combination is held out.',
            'Unannotated historical unsupported sources establish exclusions, not universal layout novelty.',
            'Nested controls retain authored local roles but no independent flat endpoint targets; no statutory semantic claim.']}
