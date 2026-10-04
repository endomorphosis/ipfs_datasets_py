"""Independent timing attachment audit, with no actual current fresh reads."""
from copy import deepcopy
from pathlib import Path
import pytest
from scripts.ops.legal_ir import prepare_legal_timing_ownership_corpus as corpus
from scripts.ops.legal_ir import summarize_legal_timing_ownership_annotations as audit


def replace(value,old,new):
    if isinstance(value,str):return value.replace(old,new).replace(old.lower(),new.lower())
    if isinstance(value,list):return [replace(v,old,new) for v in value]
    if isinstance(value,dict):return {k:replace(v,old,new) for k,v in value.items()}
    return value


def fictional_singles(rows,labels,pairs):
    newrows=replace(deepcopy(rows),'Beech','Maple');newlabels=replace(deepcopy(labels),'Beech','Maple')
    identities={old['id']:'timing-'+audit.text_sha(new['source_text']) for old,new in zip(rows,newrows,strict=True)}
    cases={a['case_group']:'case-'+audit.text_sha('fictional/'+a['case_group']) for a in labels}
    for row in newrows:row['id']=identities[row['id']]
    lookup={r['id']:r for r in newrows}
    for a in newlabels:
        a['id']=identities[a['id']];a['source_sha256']=audit.text_sha(lookup[a['id']]['source_text']);a['panel']='fresh';a['case_group']=cases[a['case_group']]
        a['role_masked_layout']=audit.independent_layout(lookup[a['id']]);a['layout_sha256']=audit.text_sha(a['role_masked_layout'])
    newpairs=[]
    for p in pairs:
        group=cases[p['case_group']];left,right=identities[p['left_id']],identities[p['right_id']]
        newpairs.append({'pair_id':group,'case_group':group,'left_id':left,'right_id':right,'canonical_ir_sha256':audit.digest(lookup[left]['canonical_ir'])})
    return newrows,newlabels,newpairs


def fictional_documents(rows,labels,pairs):
    newrows=replace(deepcopy(rows),'Cedar','Hazel');newlabels=replace(deepcopy(labels),'Cedar','Hazel')
    identities={old['candidate_id']:'document-'+audit.text_sha(new['source_text']) for old,new in zip(rows,newrows,strict=True)}
    cases={a['case_group']:'case-'+audit.text_sha('fictional/'+a['case_group']) for a in labels}
    for row in newrows:row['candidate_id']=identities[row['candidate_id']];row['source_sha256']=audit.text_sha(row['source_text'])
    lookup={r['candidate_id']:r for r in newrows}
    for a in newlabels:
        a['candidate_id']=identities[a['candidate_id']];a['source_sha256']=lookup[a['candidate_id']]['source_sha256'];a['panel']='document_fresh';a['case_group']=cases[a['case_group']]
    ann={a['candidate_id']:a for a in newlabels};newpairs=[]
    for p in pairs:
        left,right=identities[p['independent_id']],identities[p['nested_id']];row=lookup[left]
        newpairs.append({'pair_id':'pair-'+audit.text_sha('fictional/'+p['pair_id']),'case_group':cases[p['case_group']],
            'independent_id':left,'nested_id':right,'local_clause_body_sha256':[audit.text_sha(row['source_text'][c['char_start']:c['char_end']]) for c in ann[left]['local_clause_coordinates']]})
    return newrows,newlabels,newpairs


@pytest.fixture(scope='module')
def fixture():
    oldrows,oldlabels,oldpairs=corpus.previous.make_panel('train');oldblocks=corpus.previous.make_blocks(oldrows,oldpairs,oldlabels)
    rows,labels,pairs=corpus.make_panel('train');tune,tlabels,tpairs=corpus.make_panel('tuning');blocks=corpus.make_blocks(rows,pairs,labels)
    fresh,flabels,fpairs=fictional_singles(tune,tlabels,tpairs)
    docs,dlabels,dpairs=corpus.make_documents('document_tuning');freshdocs,fdlabels,fdpairs=fictional_documents(docs,dlabels,dpairs)
    packs={'new':corpus.previous.oracle_pack(docs,dlabels),'fresh':corpus.previous.oracle_pack(freshdocs,fdlabels)}
    main=[{'id':f'old-{i}','source_text':f'frozen main fixture {i}'} for i in range(4080)]
    refs={k:{'path':'fictional/'+k,'sha256':'0'*64,'bytes':1} for k in ('aux_rows','aux_pairs','aux_blocks')}
    prior={'legacy':{'training':main},'manifest':{'artifacts':refs},'aux_rows':oldrows,'aux_pairs':oldpairs,'aux_blocks':oldblocks,
           'training_annotation_ledger':{'single_rows':oldlabels,'document_rows':[]}}
    split={'case_groups':384,'cross_split_source_overlap':0,'cross_split_meaning_overlap':0,'cross_split_case_overlap':0,'grammar_and_templates_shared':True,'structural_novelty_claimed':False}
    inputs={'manifest':{'schema':'authored-legal-timing-ownership-corpus/v1','main_training_sha256':audit.digest(main),'retained_auxiliary_refs':refs,'split_audit':split},
        'prior_role_inputs':prior,'legacy':prior['legacy'],'aux_rows':oldrows+rows,'aux_pairs':oldpairs+pairs,'aux_blocks':oldblocks+blocks,
        'ownership_rows':rows,'ownership_pairs':pairs,'ownership_blocks':blocks,'new_tuning':tune,'tuning_pairs':tpairs,
        'fresh_sources':[corpus.source_row(r) for r in fresh],'document_tuning':docs,'document_tuning_pairs':dpairs,
        'fresh_document_sources':[corpus.document_source(r) for r in freshdocs],
        **{'oracle_'+k:{'new':packs['new'][k]} for k in ('sources','targets','occurrences','boundaries','document_sources')},
        'training_annotation_ledger':{'single_rows':oldlabels+labels,'document_rows':[]},
        'ownership_training_annotation_ledger':{'single_rows':labels,'document_rows':[]},
        'tuning_annotation_ledger':{'single_rows':tlabels,'document_rows':dlabels}}
    ledger={'schema':'legal-timing-ownership-annotations/v1','single_rows':labels+tlabels+flabels,'document_rows':dlabels+fdlabels}
    history={'prior_role_train':oldrows};history_sources=[r['source_text'] for r in oldrows]
    pools={**history,'new_ownership_train':rows,'new_ownership_tuning':tune,'new_ownership_document_tuning':packs['new']['targets']}
    layouts={p:{audit.independent_layout(r) for r in values} for p,values in pools.items()};evidence=[]
    for panel,values in (('single',fresh),('oracle_document',packs['fresh']['targets'])):
        for row in values:
            layout=audit.independent_layout(row);matches=sorted(k for k,v in layouts.items() if layout in v)
            evidence.append({'id':row['id'],'panel':panel,'source_sha256':audit.text_sha(row['source_text']),'role_masked_layout':layout,
                'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination',
                'matched_new_ownership_training':'new_ownership_train' in matches})
    exposure={'known_pool_counts':{p:len(v) for p,v in pools.items()},'known_role_masked_layouts':{p:sorted(v) for p,v in layouts.items()},
        'prior_source_hashes_sha256':audit.digest(sorted(audit.text_sha(audit.normalize(s)) for s in history_sources)),
        'new_source_overlap':0,'rows':evidence,'structural_novelty_claimed':False,'split_audit':split}
    return {'args':[inputs,fresh,fpairs,freshdocs,fdpairs,packs['fresh']['targets'],ledger,exposure],
        'kwargs':{'historical_layout_pools':history,'historical_source_inventory':history_sources,
            'fresh_oracle_inputs':{k:packs['fresh'][k] for k in ('sources','occurrences','boundaries','document_sources')}}}


def run(f):return audit.audit_timing_annotations(*f['args'],**f['kwargs'])


def test_complete_new_audit_preserves_old576_and_main4080(fixture):
    result=run(fixture)
    assert (result['main_training_rows'],result['retained_auxiliary_rows'],result['new_auxiliary_rows'],result['combined_auxiliary_rows'])==(4080,576,192,768)
    assert result['combined_pairs']==384 and result['combined_blocks']==192 and result['new_blocks']==48
    assert result['new_case_groups']==384
    assert result['new_single_panels']['fresh']['ownership_classes']=={k:48 for k in audit.CLASSES}


def test_document_oracle_keeps_all120_supported_occurrences(fixture):
    result=run(fixture)['new_document_panels']['document_fresh']
    assert result['documents']==48 and result['occurrences']==120 and result['repeated_occurrences_retained']==6
    assert sum(result['supported_occurrence_ownership'].values())==120 and result['unsupported_denominator']==0


def test_no_file_access_from_pure_helper(fixture,monkeypatch):
    def deny(*args,**kwargs):raise AssertionError('unexpected file read')
    monkeypatch.setattr(Path,'read_bytes',deny);monkeypatch.setattr(Path,'read_text',deny);monkeypatch.setattr(Path,'open',deny)
    assert run(fixture)['statutory_gold_verified'] is False


@pytest.mark.parametrize('key',['owner','relation','char_start','source_text','timing_ownership'])
def test_repaired_hash_cannot_move_timing_to_wrong_owner(fixture,key):
    f=deepcopy(fixture);a=next(a for a in f['args'][6]['single_rows'] if a['panel']=='fresh' and a['timing_ownership']=='condition_only')
    p=a['timing_role_spans'][0]
    if key=='owner':p[key]='temporal'
    elif key=='relation':p[key]='independent_action_deadline'
    elif key=='char_start':p[key]-=1
    elif key=='source_text':p[key]='within1day'
    else:a[key]='deadline_only'
    with pytest.raises(ValueError):run(f)


def test_both_class_cannot_drop_one_timing_pointer(fixture):
    f=deepcopy(fixture);a=next(a for a in f['args'][6]['single_rows'] if a['panel']=='fresh' and a['timing_ownership']=='both')
    a['timing_role_spans'].pop()
    with pytest.raises(ValueError):run(f)


def test_absent_deadline_cannot_receive_condition_span(fixture):
    f=deepcopy(fixture);r=next(r for r in f['args'][1] if r['canonical_ir']['rules'][0]['conditions'] and not r['canonical_ir']['rules'][0]['temporal'])
    r['facet_spans']['temporal']=r['facet_spans']['conditions']
    with pytest.raises(ValueError):run(f)


def test_document_global_timing_span_offset_checked(fixture):
    f=deepcopy(fixture)
    c=next(c for a in f['args'][6]['document_rows'] if a['panel']=='document_fresh' for c in a['local_clause_coordinates'] if c['timing_role_spans'])
    c['timing_role_spans'][0]['char_end']+=1
    with pytest.raises(ValueError):run(f)


def test_exact_old_auxiliary_prefix_cannot_be_reordered(fixture):
    f=deepcopy(fixture);rows=f['args'][0]['aux_rows'];rows[0],rows[1]=rows[1],rows[0]
    with pytest.raises(ValueError,match='prefix'):run(f)


def test_old_auxiliary_refs_must_stay_exact(fixture):
    f=deepcopy(fixture);f['args'][0]['manifest']['retained_auxiliary_refs']=deepcopy(f['args'][0]['manifest']['retained_auxiliary_refs'])
    f['args'][0]['manifest']['retained_auxiliary_refs']['aux_rows']['sha256']='1'*64
    with pytest.raises(ValueError,match='reference'):run(f)


def test_new_noncomplementary_block_rejected(fixture):
    f=deepcopy(fixture);b=f['args'][0]['ownership_blocks'][0];b['pair_ids'][1]=f['args'][0]['ownership_blocks'][1]['pair_ids'][0];b['block_id']='block-'+audit.digest(b['pair_ids'])
    with pytest.raises(ValueError):run(f)


def test_exposed_source_copy_into_new_panel_detected(fixture):
    f=deepcopy(fixture);f['kwargs']['historical_source_inventory'].append(f['args'][1][0]['source_text'])
    with pytest.raises(ValueError,match='history'):run(f)


def test_shared_template_claim_and_exposure_evidence_reconstructed(fixture):
    result=run(fixture)
    assert result['fresh_layouts']['single']=={'matched_local_layout':192}
    assert not result['structural_novelty_claimed']
    f=deepcopy(fixture);f['args'][7]['structural_novelty_claimed']=True
    with pytest.raises(ValueError):run(f)


def test_dropped_oracle_duplicate_rejected(fixture):
    f=deepcopy(fixture);f['args'][5].pop()
    with pytest.raises(ValueError):run(f)


def test_caption_is_not_part_of_actor(fixture):
    f=deepcopy(fixture);a=next(a for a in f['args'][6]['single_rows'] if a['panel']=='fresh' and a['editorial_context'])
    r=next(r for r in f['args'][1] if r['id']==a['id']);r['facet_spans']['actor'][0]=a['editorial_context'][0]['start_char']
    with pytest.raises(ValueError):run(f)
