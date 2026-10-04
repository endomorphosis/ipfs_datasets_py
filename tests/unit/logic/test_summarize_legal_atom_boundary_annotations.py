"""Independent checker tests use admitted training/tuning and fictional holdouts.

No current fresh target, pair, ledger, exposure or renderer supplies fixtures.
The ordinary admission loader may validate the current source-only inventory.
"""
from copy import deepcopy
from pathlib import Path
import random
import re
import pytest
from scripts.ops.legal_ir import prepare_legal_atom_boundary_corpus as c
from scripts.ops.legal_ir import summarize_legal_atom_boundary_annotations as audit
from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs
BASE=Path('/home/barberb/lift_coding/artifacts/legal-decoder-atom-boundary-20261003')


def rename(value,prefix):
    if isinstance(value,dict):return {k:rename(v,prefix) for k,v in value.items()}
    if isinstance(value,list):return [rename(v,prefix) for v in value]
    if isinstance(value,str):return value.replace('Hazelatom',prefix+'atom').replace('hazelatom',prefix.lower()+'atom')
    return value


def fictional_pair(case,copy):
    _,_,aa=c.make_pair('tuning',case)
    a=rename(aa[0],('Fable','Birch')[copy]);local=[]
    factors=deepcopy(a['factors']);factors['variant']+=2*copy;factors['child_structure']=audit.STRUCTURES['fresh']
    for occurrence in a['local_clause_coordinates']:
        offset=occurrence['char_start'];old=occurrence['source_text']
        fields={k:None if v is None else [x-offset for x in v] for k,v in occurrence['facet_spans'].items()}
        trigger=[x-offset for x in occurrence['trigger_span']]
        cues=[{**q,'start_char':q['start_char']-offset,'end_char':q['end_char']-offset} for q in occurrence['qualifier_cues']]
        notes=[{**n,'start_char':n['start_char']-offset,'end_char':n['end_char']-offset} for n in occurrence['editorial_context']]
        if occurrence['index']==1:
            # Complete source slices: H,T,Q,actor -> Q,T,H,actor. Endpoints are
            # mapped by interval ownership, avoiding ambiguous boundary points.
            h=notes[0]['end_char'];t=fields['temporal'][1]+2;q=fields['actor'][0]
            slices=((t,q),(h,t),(0,h),(q,len(old)))
            def move(interval):
                if interval is None:return None
                total=0
                for start,end in slices:
                    if start<=interval[0]<interval[1]<=end:return [total+interval[0]-start,total+interval[1]-start]
                    total+=end-start
                raise AssertionError('fixture span crosses a reordered source block')
            fields={k:move(v) for k,v in fields.items()};trigger=move(trigger)
            for values in (cues,notes):
                for value in values:value['start_char'],value['end_char']=move([value['start_char'],value['end_char']])
            body=''.join(old[start:end] for start,end in slices)
        else:body=old
        local.append({'source_text':body,'rule':occurrence['rule'],'facet_spans':fields,'trigger_span':trigger,
            'qualifier_cues':cues,'editorial_context':notes})
    rows=[];annotations=[];group='case-'+c.sha(f'fictional-atom-fixture/{copy}/{case}'.encode())
    for supported in (True,False):
        row,a=c._document('fresh',case+48*copy,factors,local,list(range(len(local))),supported)
        a['case_group']=group;rows.append(row);annotations.append(a)
    pair={'pair_id':'pair-'+c.sha(group.encode()),'case_group':group,'independent_id':rows[0]['candidate_id'],
        'nested_id':rows[1]['candidate_id'],'local_clause_body_sha256':[c.sha(v['source_text'].encode()) for v in local]}
    return rows,pair,annotations


@pytest.fixture(scope='module')
def bundle():
    inputs=c.load_training_inputs(BASE/'corpus-01/manifest.json')
    panels={'train':inputs['atom_train'],'tuning':inputs['new_tuning'],'fresh':[]}
    labels=[];pairs=[]
    for case in range(48):labels.extend(c.make_pair('tuning',case)[2])
    for copy in range(2):
        for case in range(48):
            rows,pair,aa=fictional_pair(case,copy);panels['fresh'].extend(rows);pairs.append(pair);labels.extend(aa)
    random.Random(924175).shuffle(panels['fresh'])
    ledger={'schema':'legal-atom-boundary-annotations/v1','document_rows':labels}
    combined={**ledger,'document_rows':inputs['training_annotation_ledger']['document_rows']+labels}
    history=c.historical_inventory();exposure=c.exposure_payload(history,panels,combined)
    inputs['sources']={'atom_fresh':[c.source_row(r) for r in panels['fresh']]}
    parent=history['prior_heading_manifest'];preservation=history['prior_preservation_manifest'];adapter=history['prior_adapter_manifest']
    kwargs={'historical_documents':{k:{'reference':v,'rows':history['pools'][k]} for k,v in history['document_references'].items()},
        'prior_annotation_ledgers':{k:{'reference':v,'ledger':history['annotation_ledgers'][k]} for k,v in history['annotation_references'].items()},
        'historical_source_inventory':{'source_texts':sorted(history['excluded_sources']),'prior_source_references':history['prior_source_references'],
            'condition_single_references':history['condition_single_references'],'real_exposed_views':86},
        'historical_manifests':{'prior_scope':c.read_ref(adapter['inputs']['prior_scope_corpus']),
            'prior_condition':c.read_ref(adapter['inputs']['prior_condition_corpus']),'prior_adapter':adapter,
            'prior_adapter_config':c.read_ref(history['prior_adapter_config_ref']),'prior_preservation':preservation,'prior_heading':parent},
        'prior_training_pairs':{'reference':parent['artifacts']['training_pairs'],'rows':inputs['training_pairs']}}
    return (inputs,panels['fresh'],pairs,ledger,exposure),kwargs


def test_complete_independent432_doc_audit_and864_masks_is_pure(bundle,monkeypatch):
    args,kwargs=bundle
    def noopen(*args,**kwargs):raise AssertionError('pure annotation audit opened a file')
    monkeypatch.setattr(Path,'open',noopen)
    result=audit.audit_atom_annotations(*args,**kwargs)
    assert result['unchanged_historical_training_documents']==1152
    assert result['new_supported_training_documents']==144 and result['new_training_rotation_pairs']==72
    assert result['new_evaluation_documents']==288 and result['fresh_layout_counts']=={'unmatched_audited_combination':192}
    assert result['training_roles']['atom_masks']['inter_clause_end_tokens']==1320
    assert result['training_roles']['atom_masks']['atom_interior_negative_tokens']==18284
    assert not result['helper_opens_files'] and not result['statutory_gold_available']


@pytest.mark.parametrize('change',[
 'inflated_atom','wrong_kind','omitted_negative','extra_negative','terminal_positive','missing_transition',
 'mask_source','unsupported_supervision','training_order','rotation_body','rotation_permutation','new_train_heading_span',
 'current_source_label','current_source_order','child_structure','temporal_offset','heading_literal','nested_attachment','flatten_nested',
 'exposure_layout','exposure_match','missing_history','old_annotation_span','old_source_commitment','train_ledger_eval_leak'])
def test_role_scope_source_exposure_and_ancestry_tampering_rejected(bundle,change):
    args,kwargs=deepcopy(bundle);inputs,targets,pairs,ledger,exposure=args
    annotations={a['candidate_id']:a for a in ledger['document_rows']}
    train_a={a['candidate_id']:a for a in inputs['training_annotation_ledger']['document_rows']}
    record=inputs['training_atom_roles'][720];row=inputs['boundary_training'][720]
    target=next(r for r in targets if r['supported']);a=annotations[target['candidate_id']];child=a['local_clause_coordinates'][1]
    if change=='inflated_atom':
        record['atom_spans'][0]['char_end']+=2
        ends={v['char_end'] for v in row['clauses']}
        record['atom_interior_negative_token_indices']=[i for i,t in enumerate(c.boundary.tokenize(row['source_text'])) if t['char_end'] not in ends
            and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in record['atom_spans'])]
    elif change=='wrong_kind':record['atom_spans'][0]['kind']='conditions'
    elif change=='omitted_negative':record['atom_interior_negative_token_indices'].pop()
    elif change=='extra_negative':record['atom_interior_negative_token_indices'].append(len(c.boundary.tokenize(row['source_text']))-1)
    elif change=='terminal_positive':record['inter_clause_end_token_indices'].append(len(c.boundary.tokenize(row['source_text']))-1)
    elif change=='missing_transition':record['inter_clause_end_token_indices'].pop()
    elif change=='mask_source':record['source_sha256']='0'*64
    elif change=='unsupported_supervision':inputs['boundary_training'][0]=next(r for r in inputs['new_train'] if not r['supported'])
    elif change=='training_order':inputs['new_train'].reverse()
    elif change=='rotation_body':inputs['atom_training_pairs'][0]['local_clause_body_sha256'][0]='0'*64
    elif change=='rotation_permutation':train_a[inputs['atom_training_pairs'][0]['rotated_id']]['body_order'].reverse()
    elif change=='new_train_heading_span':
        role=inputs['training_token_roles'][720];role['editorial_heading_spans'][0]['char_end']+=2
        role['editorial_hard_negative_token_indices']=[i for i,t in enumerate(c.boundary.tokenize(row['source_text']))
            if re.fullmatch(r'[^\w\s]',t['text']) and i not in role['true_end_token_indices'] and
            any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in role['editorial_heading_spans'])]
    elif change=='current_source_label':inputs['sources']['atom_fresh'][0]['supported']=True
    elif change=='current_source_order':inputs['sources']['atom_fresh'].reverse()
    elif change=='child_structure':a['factors']['child_structure']=audit.STRUCTURES['tuning']
    elif change=='temporal_offset':child['facet_spans']['temporal'][0]+=1
    elif change=='heading_literal':child['editorial_context'][0]['source_text']='Wrong notes.'
    elif change=='nested_attachment':annotations[next(r for r in targets if not r['supported'])['candidate_id']]['scope_attachment']['child_occurrence']=0
    elif change=='flatten_nested':next(r for r in targets if not r['supported'])['clauses']=deepcopy(target['clauses'])
    elif change=='exposure_layout':exposure['rows'][0]['role_masked_layout']+='invented'
    elif change=='exposure_match':exposure['rows'][0]['matching_pools']=['new_train']
    elif change=='missing_history':kwargs['historical_documents'].pop('prior_heading_fresh')
    elif change=='old_annotation_span':kwargs['prior_annotation_ledgers']['prior_adapter']['ledger']['document_rows'][0]['local_clause_coordinates'][1]['editorial_context'][0]['end_char']+=2
    elif change=='old_source_commitment':exposure['historical_source_inventory_sha256']='0'*64
    elif change=='train_ledger_eval_leak':inputs['training_annotation_ledger']['document_rows'][0]=deepcopy(a)
    with pytest.raises(ValueError):audit.audit_atom_annotations(*args,**kwargs)


def test_equal_atom_text_in_repeated_occurrences_gets_distinct_intervals(bundle):
    inputs=bundle[0][0]
    row=next(r for r in inputs['atom_train'] if r['repeated_rule_occurrences'])
    record=next(r for r in inputs['training_atom_roles'] if r['candidate_id']==row['candidate_id'])
    actors=[s for s in record['atom_spans'] if s['kind']=='actor']
    assert len(actors)==3 and len({(s['char_start'],s['char_end']) for s in actors})==3
    assert len(record['inter_clause_end_token_indices'])==2
