"""Independent role/occurrence checks using only admitted and fictional data."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts.ops.legal_ir import prepare_legal_role_span_rehearsal_corpus as corpus
from scripts.ops.legal_ir import summarize_legal_role_span_rehearsal_annotations as audit


def transform_strings(value,old,new):
    if isinstance(value,str):return value.replace(old,new).replace(old.lower(),new.lower())
    if isinstance(value,list):return [transform_strings(v,old,new) for v in value]
    if isinstance(value,dict):return {k:transform_strings(v,old,new) for k,v in value.items()}
    return value


def fictional_fresh_singles(tuning,labels,pairs):
    """Reorder copied admitted atoms into public proposed orders, no fresh renderer."""
    by_id={a['id']:a for a in labels};rows=[];annotations=[];ids={};case_ids={}
    for prior in tuning:
        old=by_id[prior['id']];rule=transform_strings(prior['canonical_ir']['rules'][0],'Birch','Cedar')
        w=corpus.prior.CoordinateWriter();notes=[];cues=[]
        cue_values={q['field']:q['source_text'] for q in old['qualifier_cues']}
        for role in audit.declared_order(old['family'],old['side'],'fresh'):
            if role in audit.FIELDS[3:] and not rule[role]:continue
            if role=='heading':
                text=audit.CAPTIONS[old['caption_style']];start=len(w.text);w.add(text)
                notes.append({'start_char':start,'end_char':len(w.text),'source_text':text,'author_stipulated_role':'nonoperative_editorial_context'})
            elif role=='trigger':
                w.add(prior['source_text'][slice(*prior['trigger_span'])],role);w.add(' ')
            else:
                if role in cue_values:
                    text=cue_values[role];start=len(w.text);w.add(text)
                    cues.append({'field':role,'start_char':start,'end_char':len(w.text),'source_text':text})
                value=rule[role];w.add(value[0] if isinstance(value,list) else value,role)
                w.add(', ' if role in audit.FIELDS[3:] else ' ')
        w.text=w.text.rstrip(' ,')+'.';identity='role-'+audit.text_sha(w.text);ids[prior['id']]=identity
        case_ids.setdefault(old['case_group'],'case-'+audit.text_sha('fictional/'+old['case_group']))
        row={'id':identity,'source_text':w.text,'canonical_ir':{'rules':[rule]},'facet_spans':{f:w.spans.get(f) for f in audit.FIELDS},
             'trigger_span':w.spans['trigger'],'domain':'new','trigger_supervised':True};rows.append(row)
        layout=audit.independent_layout(row)
        annotations.append({**old,'id':identity,'source_sha256':audit.text_sha(w.text),'panel':'fresh','case_group':case_ids[old['case_group']],
            'facet_spans':row['facet_spans'],'trigger_span':row['trigger_span'],'editorial_context':notes,'qualifier_cues':cues,
            'role_masked_layout':layout,'layout_sha256':audit.text_sha(layout)})
    newpairs=[];lookup={r['id']:r for r in rows}
    for p in pairs:
        group=case_ids[p['case_group']]
        newpairs.append({'pair_id':group,'case_group':group,'left_id':ids[p['left_id']],'right_id':ids[p['right_id']],
                         'canonical_ir_sha256':audit.digest(lookup[ids[p['left_id']]]['canonical_ir'])})
    return rows,annotations,newpairs


def fictional_fresh_documents(tuning,labels,pairs):
    rows=transform_strings(deepcopy(tuning),'Ash','Fir');annotations=transform_strings(deepcopy(labels),'Ash','Fir')
    idmap={old['candidate_id']:'document-'+audit.text_sha(new['source_text']) for old,new in zip(tuning,rows,strict=True)}
    casemap={a['case_group']:'case-'+audit.text_sha('fictional/'+a['case_group']) for a in annotations}
    for row in rows:row['candidate_id']=idmap[row['candidate_id']];row['source_sha256']=audit.text_sha(row['source_text'])
    sources={r['candidate_id']:r for r in rows}
    for a in annotations:
        a['candidate_id']=idmap[a['candidate_id']];a['source_sha256']=sources[a['candidate_id']]['source_sha256']
        a['panel']='document_fresh';a['case_group']=casemap[a['case_group']]
    lookup={a['candidate_id']:a for a in annotations};newpairs=[]
    for pair in pairs:
        independent=idmap[pair['independent_id']];row=sources[independent];label=lookup[independent]
        newpairs.append({'pair_id':'pair-'+audit.text_sha('fictional/'+pair['pair_id']),'case_group':casemap[pair['case_group']],
            'independent_id':independent,'nested_id':idmap[pair['nested_id']],
            'local_clause_body_sha256':[audit.text_sha(row['source_text'][v['char_start']:v['char_end']]) for v in label['local_clause_coordinates']]})
    return rows,annotations,newpairs


@pytest.fixture(scope='module')
def bundle():
    # Only TRAIN and TUNING producer branches are invoked, never current fresh.
    train,trainlabels,trainpairs=corpus.make_panel('train');tune,tunelabels,tunepairs=corpus.make_panel('tuning')
    fresh,freshlabels,freshpairs=fictional_fresh_singles(tune,tunelabels,tunepairs)
    dtune,dtunelabels,dtunepairs=corpus.make_documents('document_tuning')
    dfresh,dfreshlabels,dfreshpairs=fictional_fresh_documents(dtune,dtunelabels,dtunepairs)
    blocks=corpus.make_blocks(train,trainpairs,trainlabels)
    packs={'new':corpus.oracle_pack(dtune,dtunelabels),'fresh':corpus.oracle_pack(dfresh,dfreshlabels)}
    oldrow=corpus.temporal.render('train',corpus.temporal.FAMILIES[0],0,0,0)[0]
    historical={'fixture':[oldrow]};historical_sources=[oldrow['source_text']]
    main=[{'id':f'old-{i}','source_text':f'pinned main fixture {i}'} for i in range(4080)]
    split={'cross_split_source_overlap':0,'cross_split_meaning_overlap':0,'cross_split_case_overlap':0,'case_groups':576,
           'shared_grammar':True,'all_layouts_novel_claimed':False,'structural_absence_collapses_are_reported':True}
    ledger={'schema':'legal-role-span-rehearsal-annotations/v1','single_rows':trainlabels+tunelabels+freshlabels,'document_rows':dtunelabels+dfreshlabels}
    inputs={'manifest':{'schema':'authored-legal-role-span-rehearsal-corpus/v1','main_training_rows':4080,'main_training_sha256':audit.digest(main),'split_audit':split},
        'legacy':{'training':main},'aux_rows':train,'aux_pairs':trainpairs,'aux_blocks':blocks,'new_tuning':tune,'tuning_pairs':tunepairs,
        'fresh_sources':[corpus.source_row(r) for r in fresh],'document_tuning':dtune,'document_tuning_pairs':dtunepairs,
        'fresh_document_sources':[corpus.document_source(r) for r in dfresh],
        **{'oracle_'+kind:{'new':packs['new'][kind]} for kind in ('sources','targets','occurrences','boundaries','document_sources')},
        'training_annotation_ledger':{'single_rows':trainlabels,'document_rows':[]},
        'tuning_annotation_ledger':{'single_rows':tunelabels,'document_rows':dtunelabels}}
    pools={**historical,'new_auxiliary':train,'new_tuning':tune,'new_document_tuning':packs['new']['targets']}
    layouts={p:{audit.independent_layout(r) for r in rows} for p,rows in pools.items()};evidence=[]
    for panel,rows in (('single',fresh),('oracle_document',packs['fresh']['targets'])):
        for row in rows:
            layout=audit.independent_layout(row);matches=sorted(p for p,values in layouts.items() if layout in values)
            evidence.append({'id':row['id'],'panel':panel,'source_sha256':audit.text_sha(row['source_text']),'role_masked_layout':layout,
                'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination','matched_new_auxiliary':'new_auxiliary' in matches})
    exposure={'known_pool_counts':{p:len(v) for p,v in pools.items()},'known_role_masked_layouts':{p:sorted(v) for p,v in layouts.items()},
              'prior_source_hashes_sha256':audit.digest(sorted(audit.text_sha(audit.normalize(s)) for s in historical_sources)),
              'new_source_overlap':0,'rows':evidence,'all_layouts_novel_claimed':False,'split_audit':split}
    return {'args':[inputs,fresh,freshpairs,dfresh,dfreshpairs,packs['fresh']['targets'],ledger,exposure],
            'kwargs':{'historical_layout_pools':historical,'historical_source_inventory':historical_sources,
                      'fresh_oracle_inputs':{k:packs['fresh'][k] for k in ('sources','occurrences','boundaries','document_sources')}}}


def run(value):return audit.audit_role_span_annotations(*value['args'],**value['kwargs'])


def test_complete_fictional_audit_covers_960_singles_192_docs_and_blocks(bundle):
    result=run(bundle)
    assert result['auxiliary_rows']==576 and result['complement_blocks']==144 and result['new_cases']==576
    assert result['single_panels']['train']['headed']==504
    assert result['single_panels']['train']['condition_owned_timing_controls']==48
    assert result['oracle_panels']['document_fresh']=={'documents':48,'occurrences':120,'unique_source_substrings':114,
        'repeated_occurrences_retained':6,'scope_eligibility_supplied':True,'segmentation_supplied':True,'unsupported_denominator':0}


def test_helper_is_pure_after_fixture_construction(bundle,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('pure helper attempted a file read')
    monkeypatch.setattr(Path,'read_bytes',forbidden);monkeypatch.setattr(Path,'read_text',forbidden);monkeypatch.setattr(Path,'open',forbidden)
    assert run(bundle)['semantic_gold_verified'] is False


@pytest.mark.parametrize('field',audit.FIELDS)
def test_corrupted_role_interval_rejected(bundle,field):
    value=deepcopy(bundle);rows=value['args'][1];row=next(r for r in rows if r['facet_spans'][field])
    row['facet_spans'][field][0]+=1
    with pytest.raises(ValueError):run(value)


def test_caption_expansion_with_repaired_annotation_hash_is_rejected(bundle):
    value=deepcopy(bundle);a=next(a for a in value['args'][6]['single_rows'] if a['panel']=='fresh' and a['editorial_context'])
    row=next(r for r in value['args'][1] if r['id']==a['id']);note=a['editorial_context'][0]
    note['end_char']=row['facet_spans']['actor'][1];note['source_text']=row['source_text'][note['start_char']:note['end_char']]
    with pytest.raises(ValueError,match='editorial'):run(value)


def test_wrong_realized_family_order_is_rejected(bundle):
    value=deepcopy(bundle);a=next(a for a in value['args'][6]['single_rows'] if a['panel']=='fresh' and a['family']=='front_interposed' and a['presence_mask']==7)
    a['family']='caption_displacement'
    with pytest.raises(ValueError):run(value)


def test_canonical_pair_hash_cannot_hide_different_meaning(bundle):
    value=deepcopy(bundle);pair=value['args'][2][0];rows={r['id']:r for r in value['args'][1]};right=rows[pair['right_id']]
    right['canonical_ir']['rules'][0]['modality']='F'
    pair['canonical_ir_sha256']=audit.digest(right['canonical_ir'])
    with pytest.raises(ValueError):run(value)


def test_complement_block_reuse_rejected(bundle):
    value=deepcopy(bundle);blocks=value['args'][0]['aux_blocks'];blocks[1]['pair_ids']=blocks[0]['pair_ids'];blocks[1]['block_id']='block-'+audit.digest(blocks[1]['pair_ids'])
    with pytest.raises(ValueError):run(value)


def test_condition_owned_time_is_not_action_deadline(bundle):
    value=deepcopy(bundle);a=next(a for a in value['args'][6]['single_rows'] if a['panel']=='fresh' and a['condition_owned_temporal_language'])
    a['condition_owned_temporal_language']=False
    with pytest.raises(ValueError,match='opaque'):run(value)


@pytest.mark.parametrize('kind',['canonical','relative_span','missing_occurrence','duplicate_id','wrong_document','interval'])
def test_oracle_target_and_occurrence_tampering_rejected(bundle,kind):
    value=deepcopy(bundle);targets=value['args'][5];pack=value['kwargs']['fresh_oracle_inputs']
    if kind=='canonical':targets[0]['canonical_ir']['rules'][0]['actor']='unrelated actor'
    elif kind=='relative_span':targets[0]['facet_spans']['actor'][0]+=1
    elif kind=='missing_occurrence':targets.pop();pack['sources'].pop();pack['occurrences'].pop()
    elif kind=='duplicate_id':targets[1]['id']=targets[0]['id']
    elif kind=='wrong_document':pack['occurrences'][0]['document_id']=pack['occurrences'][-1]['document_id']
    else:pack['occurrences'][0]['char_end']-=1
    with pytest.raises(ValueError):run(value)


def test_nested_guard_cannot_acquire_flat_supported_gold(bundle):
    value=deepcopy(bundle);row=next(r for r in value['args'][3] if not r['supported']);row['supported']=True
    with pytest.raises(ValueError):run(value)


def test_nested_attachment_relation_span_rejected(bundle):
    value=deepcopy(bundle);a=next(a for a in value['args'][6]['document_rows'] if a['panel']=='document_fresh' and not a['supported'])
    a['scope_attachment']['start_char']+=1
    with pytest.raises(ValueError,match='nested'):run(value)


def test_exposure_layout_and_novelty_claim_recomputed(bundle):
    value=deepcopy(bundle);value['args'][7]['rows'][0]['matching_pools']=['invented']
    with pytest.raises(ValueError,match='exposure'):run(value)
    value=deepcopy(bundle);value['args'][7]['all_layouts_novel_claimed']=True
    with pytest.raises(ValueError,match='novelty'):run(value)


def test_historical_source_overlap_detected_even_with_new_ids(bundle):
    value=deepcopy(bundle);value['kwargs']['historical_source_inventory'].append(value['args'][1][0]['source_text'])
    with pytest.raises(ValueError,match='history'):run(value)


def test_main_training_changed_after_binding_rejected(bundle):
    value=deepcopy(bundle);value['args'][0]['legacy']['training'][0]['source_text']='changed'
    with pytest.raises(ValueError,match='main4080'):run(value)


def test_layout_masker_matches_frozen_admitted_implementation(bundle):
    inputs=bundle['args'][0]
    for row in inputs['aux_rows']+inputs['new_tuning']:
        assert audit.independent_layout(row)==corpus.temporal.role_layout(row)


def test_shared_grammar_and_absent_facet_collapses_remain_visible(bundle):
    result=run(bundle)
    assert sum(result['fresh_layouts']['single'].values())==192
    assert sum(result['fresh_layouts']['oracle_document'].values())==120
    assert not result['semantic_gold_verified']
