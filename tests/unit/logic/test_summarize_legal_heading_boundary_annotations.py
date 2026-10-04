"""Independent audit fixtures use admitted tuning bodies with fictional entities.

Current production fresh sources/targets/render branch are not used.
"""
from copy import deepcopy
from pathlib import Path
import random
import re
import pytest
from scripts.ops.legal_ir import prepare_legal_heading_boundary_corpus as c
from scripts.ops.legal_ir import summarize_legal_heading_boundary_annotations as audit
from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs


def rename(v,prefix):
    if isinstance(v,dict):return {k:rename(x,prefix) for k,x in v.items()}
    if isinstance(v,list):return [rename(x,prefix) for x in v]
    if isinstance(v,str):return v.replace('Silverheading',prefix+'heading').replace('silverheading',prefix.lower()+'heading')
    return v


def fictional_pair(heading_index,subcase):
    # Four fictional variants from admitted tuning bodies; no fresh rendering call.
    family=audit.FAMILIES_BY_PANEL['fresh'][heading_index]
    source_case=(heading_index%2)*24+subcase
    original,_,labels=c.make_pair('tuning',source_case)
    prefix=('Fablea','Fableb','Fablec','Fabled')[heading_index]
    local=[]
    for occurrence in rename(labels[0]['local_clause_coordinates'],prefix):
        offset=occurrence['char_start'];old=occurrence['source_text']
        fields={k:None if v is None else [p-offset for p in v] for k,v in occurrence['facet_spans'].items()}
        trigger=[p-offset for p in occurrence['trigger_span']]
        cues=[{**q,'start_char':q['start_char']-offset,'end_char':q['end_char']-offset} for q in occurrence['qualifier_cues']]
        if occurrence['index']==1:
            note=occurrence['editorial_context'][0];removed=note['end_char']-note['start_char'];replacement=audit.HEADINGS[family]
            temporal=fields['temporal'];deadline=(temporal[1]-removed+2) if temporal is not None and family=='caption_after_time' else 0
            def point(x):return x-removed+(len(replacement) if x>=removed+deadline else 0)
            body=old[removed:removed+deadline]+replacement+old[removed+deadline:]
            fields={k:None if v is None else [point(p) for p in v] for k,v in fields.items()}
            trigger=[point(p) for p in trigger]
            cues=[{**q,'start_char':point(q['start_char']),'end_char':point(q['end_char'])} for q in cues]
            editorial=[{'start_char':deadline,'end_char':deadline+len(replacement),'source_text':replacement,
                'author_stipulated_role':'nonoperative_editorial_context'}]
        else:body=old;editorial=[]
        local.append({'source_text':body,'rule':occurrence['rule'],'facet_spans':fields,'trigger_span':trigger,
            'qualifier_cues':cues,'editorial_context':editorial})
    case=heading_index*24+subcase;group='case-'+c.sha(('fictional-heading/'+str(case)).encode())
    factors=deepcopy(labels[0]['factors']);factors['heading']=family
    rows,annotations=[],[]
    for supported in (True,False):
        text='';occurrences=[];declarations=[];attachment=None
        for i,item in enumerate(local):
            if i:
                if not supported and i==1:
                    cue=' unless ';start=len(text);text+=cue
                    attachment={'start_char':start,'end_char':len(text),'source_text':cue,'parent_occurrence':0,'child_occurrence':1,
                        'declared_relation':'nested_normative_exception_outside_flat_profile'}
                else:text+='\n'
            start=len(text);text+=item['source_text'];end=len(text)
            occurrences.append({'index':i,'char_start':start,'char_end':end,'source_text':item['source_text'],
                'source_sha256':c.sha(item['source_text'].encode()),'rule':deepcopy(item['rule']),
                'facet_spans':{k:None if v is None else [p+start for p in v] for k,v in item['facet_spans'].items()},
                'trigger_span':[p+start for p in item['trigger_span']],
                'qualifier_cues':[{**q,'start_char':q['start_char']+start,'end_char':q['end_char']+start} for q in item['qualifier_cues']],
                'editorial_context':[{**q,'start_char':q['start_char']+start,'end_char':q['end_char']+start} for q in item['editorial_context']]})
            if supported or i!=0:text+='.'
            if supported:declarations.append({'char_start':start,'char_end':len(text),'rule':deepcopy(item['rule'])})
        source_hash=c.sha(text.encode());identity='scope-'+source_hash
        repeated=len({c.boundary.digest(x['rule']) for x in local})<len(local)
        row={'candidate_id':identity,'source_text':text,'source_sha256':source_hash,'supported':supported,
            'construction':family if supported else 'unsupported/nested_normative_exception','repeated_rule_occurrences':repeated if supported else False,
            'clauses':declarations,'unsupported_reason':None if supported else 'nested_normative_exception',
            'label_origin':'authored_scope_contrast_not_statutory_gold'}
        annotation={'candidate_id':identity,'source_sha256':source_hash,'panel':'fresh','case_group':group,'family':family,'factors':factors,
            'supported':supported,'side':'independent' if supported else 'nested','local_clause_coordinates':occurrences,
            'scope_attachment':attachment,'annotation_authority':'author_stipulated_flat_profile_eligibility_not_semantic_truth'}
        rows.append(row);annotations.append(annotation)
    pair={'pair_id':'pair-'+c.sha(group.encode()),'case_group':group,'independent_id':rows[0]['candidate_id'],
        'nested_id':rows[1]['candidate_id'],'local_clause_body_sha256':[c.sha(v['source_text'].encode()) for v in local]}
    return rows,pair,annotations


@pytest.fixture(scope='module')
def bundle():
    panels,pairs,labels={}, {}, []
    for panel in ('tuning','fresh'):
        panels[panel],pairs[panel]=[],[]
        cases=[(None,i) for i in range(48)] if panel=='tuning' else [(h,i) for h in range(4) for i in range(24)]
        for heading,case in cases:
            rows,pair,annotations=c.make_pair('tuning',case) if panel=='tuning' else fictional_pair(heading,case)
            panels[panel].extend(rows);pairs[panel].append(pair);labels.extend(annotations)
        random.Random(c.SHUFFLE_SEED+list(c.COUNTS).index(panel)).shuffle(panels[panel])
    ledger={'schema':'legal-heading-boundary-annotations/v1','document_rows':labels}
    history=c.historical_inventory();parent=history['prior_preservation_manifest']
    old_adapter=history['prior_adapter_manifest'];old_config=c.read_ref(history['prior_adapter_config_ref'])
    old_scope=c.read_ref(old_adapter['inputs']['prior_scope_corpus']);old_condition=c.read_ref(old_adapter['inputs']['prior_condition_corpus'])
    exposure=c.exposure_payload(history,panels,ledger)
    train=history['pools']['prior_adapter_train'];replay={k:history['pools'][k] for k in history['replay_references']}
    fit=[r for rows in replay.values() for r in rows if r['supported']]+[r for r in train if r['supported']]
    role_ledgers={k:history['annotation_ledgers'][k] for k in ('prior_scope','prior_adapter')}
    parent_pairs=c.read_ref(parent['artifacts']['training_pairs'])
    manifest={'schema':c.SCHEMA,'training_reused_without_changes':True,'new_training_documents':0,'training_documents':1152,
        'artifacts':history['training_references'],'replay_references':history['replay_references'],
        'retention_target_references':history['retention_target_references'],
        'training_annotation_references':{k:history['annotation_references'][k] for k in role_ledgers}}
    inputs={'manifest':manifest,'new_train':train,'training_pairs':parent_pairs,'replay':replay,'boundary_training':fit,
        'training_token_roles':c.training_token_roles(fit,role_ledgers),'tuning_pairs':pairs['tuning'],
        'tuning':{**{k:c.read_ref(v) for k,v in history['retention_target_references'].items()},'heading_new':panels['tuning']},
        'sources':{'heading_fresh':[c.source_row(r) for r in panels['fresh']]}}
    kwargs={'historical_documents':{k:{'reference':v,'rows':history['pools'][k]} for k,v in history['document_references'].items()},
        'prior_annotation_ledgers':{k:{'reference':v,'ledger':history['annotation_ledgers'][k]} for k,v in history['annotation_references'].items()},
        'historical_source_inventory':{'source_texts':sorted(history['excluded_sources']),'prior_source_references':history['prior_source_references'],
            'condition_single_references':history['condition_single_references'],'real_exposed_views':86},
        'historical_manifests':{'prior_scope':old_scope,'prior_condition':old_condition,'prior_adapter':old_adapter,
            'prior_adapter_config':old_config,'prior_preservation':parent},
        'prior_training_pairs':{'reference':parent['artifacts']['training_pairs'],'rows':parent_pairs}}
    return (inputs,panels['fresh'],pairs['fresh'],ledger,exposure),kwargs


def test_full288_eval_annotations_structural_holdout_and_independent720_train_roles_no_io(bundle,monkeypatch):
    args,kwargs=bundle
    def forbidden(*args,**kwargs):raise AssertionError('pure audit opened a file')
    monkeypatch.setattr(Path,'open',forbidden)
    result=audit.audit_heading_annotations(*args,**kwargs)
    assert result['new_evaluation_documents']==288 and result['new_scope_pairs']==144
    assert result['training_token_roles']['true_end_tokens']==1824
    assert result['training_token_roles']['editorial_punctuation_negative_tokens']==864
    assert result['training_token_roles']['unsupported_documents_excluded']==432
    assert result['fresh_heading_structures_unmatched_after_lexical_number_whitespace_normalization']
    assert result['fresh_layout_counts']=={'unmatched_audited_combination':192}
    assert not result['helper_opens_files']


@pytest.mark.parametrize('change',['inflated_mask_span','missing_negative','wrong_endpoint','unsupported_mask','mask_source','train_order',
 'heading_factor','heading_literal','time_order','scope_attachment','flatten_guard','source_label','source_order',
 'structural_signature','structural_pool','historical_structure','historical_heading_gap','prior_annotation_span','full_layout','history_source_commitment'])
def test_source_masks_structural_holdout_and_provenance_tampering_rejected(bundle,change):
    args,kwargs=deepcopy(bundle);inputs,targets,pairs,ledger,exposure=args
    inputs=deepcopy(inputs);args=(inputs,targets,pairs,ledger,exposure)
    annotations={a['candidate_id']:a for a in ledger['document_rows']}
    row=next(r for r in targets if r['supported'] and annotations[r['candidate_id']]['factors']['heading']=='caption_after_time'
        and annotations[r['candidate_id']]['factors']['child_time_kind']=='hours')
    a=annotations[row['candidate_id']];child=a['local_clause_coordinates'][1]
    role=next(r for r in inputs['training_token_roles'] if r['editorial_heading_spans'])
    if change=='inflated_mask_span':
        role['editorial_heading_spans'][0]['char_end']+=3
        train=next(r for r in inputs['boundary_training'] if r['candidate_id']==role['candidate_id'])
        role['editorial_hard_negative_token_indices']=[i for i,t in enumerate(c.boundary.tokenize(train['source_text']))
            if re.fullmatch(r'[^\w\s]',t['text']) and i not in role['true_end_token_indices'] and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in role['editorial_heading_spans'])]
    elif change=='missing_negative':role['editorial_hard_negative_token_indices'].pop()
    elif change=='wrong_endpoint':role['true_end_token_indices'][0]-=1
    elif change=='unsupported_mask':inputs['boundary_training'][0]=next(r for r in inputs['new_train'] if not r['supported'])
    elif change=='mask_source':role['source_sha256']='0'*64
    elif change=='train_order':inputs['new_train'].reverse()
    elif change=='heading_factor':a['factors']['heading']='split_citation'
    elif change=='heading_literal':child['editorial_context'][0]['source_text']='Other heading.'
    elif change=='time_order':child['facet_spans']['temporal'][0]+=1
    elif change=='scope_attachment':
        neg=next(r for r in targets if not r['supported']);annotations[neg['candidate_id']]['scope_attachment']['child_occurrence']=0
    elif change=='flatten_guard':next(r for r in targets if not r['supported'])['clauses']=deepcopy(row['clauses'])
    elif change=='source_label':inputs['sources']['heading_fresh'][0]['supported']=True
    elif change=='source_order':inputs['sources']['heading_fresh'].reverse()
    elif change=='structural_signature':exposure['rows'][0]['heading_structures'][0]['marker_pattern']='H .'
    elif change=='structural_pool':exposure['rows'][0]['structural_matching_pools']=['prior_adapter_train']
    elif change=='historical_structure':exposure['historical_heading_structure_rows']['prior_adapter_train'][0]['heading_structure_sha256']='0'*64
    elif change=='historical_heading_gap':exposure['historical_heading_unannotated_ids']['original']=[]
    elif change=='prior_annotation_span':kwargs['prior_annotation_ledgers']['prior_adapter']['ledger']['document_rows'][0]['local_clause_coordinates'][1]['editorial_context'][0]['end_char']+=3
    elif change=='full_layout':exposure['rows'][0]['role_masked_layout']+='invented'
    else:exposure['historical_source_inventory_sha256']='0'*64
    with pytest.raises(ValueError):audit.audit_heading_annotations(*args,**kwargs)


def test_normalized_marker_signature_ignores_words_numbers_whitespace():
    o={'editorial_context':[{'source_text':'[2]\nFiling duty.—\n','start_char':0}], 'facet_spans':{'temporal':None}}
    p=deepcopy(o);p['editorial_context'][0]['source_text']='[833] Archive responsibility.— '
    assert audit.heading_structure(o)==audit.heading_structure(p)
    p['facet_spans']['temporal']=[0,7];p['editorial_context'][0]['start_char']=9
    assert audit.heading_structure(o)!=audit.heading_structure(p)
