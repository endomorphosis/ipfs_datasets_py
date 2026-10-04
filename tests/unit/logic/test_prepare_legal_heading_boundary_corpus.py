"""Heading structure holdout and source-bound TRAIN endpoint mask checks."""
from collections import Counter
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import re
import pytest
from scripts.ops.legal_ir import prepare_legal_heading_boundary_corpus as c

@pytest.fixture(scope='module')
def authored():return c.make_panels()

@pytest.fixture(scope='module')
def history():return c.historical_inventory()


def test_full_eval_heading_factorial_balanced_classes_and_no_train_generation(authored):
    panels,pairs,ledger,counts=authored;lookup={a['candidate_id']:a for a in ledger['document_rows']}
    assert set(panels)=={'tuning','fresh'} and len(ledger['document_rows'])==288
    for panel,n in c.COUNTS.items():
        assert len(pairs[panel])==n//2
        witnessed={tuple(lookup[p['independent_id']]['factors'][k] for k in ('heading','first_modality','child_time_kind','clause_count')) for p in pairs[panel]}
        assert witnessed==set(product(c.FAMILIES_BY_PANEL[panel],'OPF',c.TIME_KINDS,(2,3)))
        for side in (True,False):
            labels=[lookup[r['candidate_id']] for r in panels[panel] if r['supported'] is side]
            for key,values in (('heading',c.FAMILIES_BY_PANEL[panel]),('first_modality','OPF'),('child_time_kind',c.TIME_KINDS),('clause_count',(2,3)),('first_CE_mask',range(4))):
                assert Counter(a['factors'][key] for a in labels)=={v:n//(2*len(values)) for v in values}
    with pytest.raises(ValueError):c.make_pair('train',0)


def test_exact_paired_body_coordinates_and_heading_time_orders(authored):
    panels,pairs,ledger,_=authored;lookup={a['candidate_id']:a for a in ledger['document_rows']}
    before=after=0
    for panel,rows in panels.items():
        c.validate_pairs(rows,pairs[panel],len(rows)//2)
        for r in rows:
            a=lookup[r['candidate_id']];c.validate_document(r,a)
            assert len(c.boundary.tokenize(r['source_text']))<=512
            child=a['local_clause_coordinates'][1]
            for s in c.heading_structure(child):
                before+=s['temporal_relative_order']=='before_heading';after+=s['temporal_relative_order']=='after_heading'
        for p in pairs[panel]:
            x,y=(lookup[p[k]] for k in ('independent_id','nested_id'))
            assert [o['source_text'] for o in x['local_clause_coordinates']]==[o['source_text'] for o in y['local_clause_coordinates']]
            assert [o['rule'] for o in x['local_clause_coordinates']]==[o['rule'] for o in y['local_clause_coordinates']]
    assert before==36 and after==180


def test_marker_normalization_cannot_claim_vocabulary_number_or_newline_novelty():
    a={'editorial_context':[{'source_text':'Filing duty [2]: ', 'start_char':0,'end_char':17}], 'facet_spans':{'temporal':None}}
    b=deepcopy(a);b['editorial_context'][0]['source_text']='Archive\nresponsibility [947]: '
    assert c.heading_structure(a)==c.heading_structure(b)
    b['editorial_context'][0]['source_text']='[947] Archive responsibility: '
    assert c.heading_structure(a)!=c.heading_structure(b)


def test_fresh_full_layouts_and_marker_patterns_absent_against_prior_and_tuning(authored,history):
    panels,_,ledger,_=authored;e=c.exposure_payload(history,panels,ledger)
    assert len(e['rows'])==192 and all(not r['matching_pools'] and not r['structural_matching_pools'] for r in e['rows'])
    assert 'prior_preservation_fresh' in e['historical_document_references']
    assert any(e['historical_heading_unannotated_ids'].values())
    known=deepcopy(history)
    sample=e['rows'][0]
    known['layout_rows']['injected']=[{'candidate_id':'old','source_sha256':'0'*64,'role_masked_layout':sample['role_masked_layout']}]
    known['heading_structure_rows']['injected']=[]
    with pytest.raises(ValueError,match='already exposed'):c.exposure_payload(known,panels,ledger)


def test_sources_opaque_unlabeled_shuffled_and_disjoint(authored):
    panels,pairs,ledger,_=authored;sets=[]
    for panel,rows in panels.items():
        assert all(set(c.source_row(r))==c.SOURCE_KEYS and re.fullmatch('scope-[0-9a-f]{64}',r['candidate_id']) for r in rows)
        assert [r['supported'] for r in rows] != [i%2==0 for i in range(len(rows))]
        sets.append(({c.temporal.prior.normalized_source(r['source_text']) for r in rows},{p['case_group'] for p in pairs[panel]},
            {c.boundary.digest(o['rule']) for a in ledger['document_rows'] if a['panel']==panel for o in a['local_clause_coordinates']}))
    assert all(not a&b for a,b in zip(*sets))


def supported_train(history):
    parent=history['prior_preservation_manifest']
    replay={k:c.read_ref(v) for k,v in parent['replay_references'].items()}
    heading=c.read_ref(parent['artifacts']['new_training_targets'])
    return [r for rows in replay.values() for r in rows if r['supported']]+[r for r in heading if r['supported']]


def test_all720_supported_train_masks_have_exact_ends_and_all_editorial_punctuation(history):
    rows=supported_train(history)
    roles=c.training_token_roles(rows,{k:history['annotation_ledgers'][k] for k in ('prior_scope','prior_adapter')})
    assert len(roles)==720 and len({r['candidate_id'] for r in roles})==720
    for row,role in zip(rows,roles,strict=True):
        tokens=c.boundary.tokenize(row['source_text']);ends={x['char_end'] for x in row['clauses']}
        positives=[i for i,t in enumerate(tokens) if t['char_end'] in ends]
        negatives=[i for i,t in enumerate(tokens) if re.fullmatch(r'[^\w\s]',t['text']) and i not in positives
            and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in role['editorial_heading_spans'])]
        assert role['true_end_token_indices']==positives and role['editorial_hard_negative_token_indices']==negatives
        assert not set(positives)&set(negatives) and set(role)==c.ROLE_KEYS
    assert all(r['editorial_hard_negative_token_indices'] for r in roles[-192:])
    assert c.role_counts(roles)['heading_bearing_documents']==240


def test_unsupported_rows_never_get_zero_boundary_targets(history):
    row=next(r for r in history['pools']['prior_adapter_train'] if not r['supported'])
    with pytest.raises(ValueError,match='no boundary supervision'):c.training_token_roles([row],{})


@pytest.mark.parametrize('mutation',['heading','time_order','heading_span','trigger','role','attachment','flatten','identity'])
def test_direct_annotations_reject_tampering(mutation):
    case=next(i for i,f in enumerate(c.factor_schedule('fresh')) if f['heading']=='caption_after_time' and f['child_time_kind']=='hours')
    rows,_,labels=c.make_pair('fresh',case);row,a=deepcopy((rows[1],labels[1]));child=a['local_clause_coordinates'][1]
    if mutation=='heading':a['factors']['heading']='split_citation'
    elif mutation=='time_order':child['facet_spans']['temporal'][0]+=1
    elif mutation=='heading_span':child['editorial_context'][0]['start_char']+=1
    elif mutation=='trigger':child['trigger_span'][0]+=1
    elif mutation=='role':child['rule']['actor']='Different actor'
    elif mutation=='attachment':a['scope_attachment']['start_char']+=1
    elif mutation=='flatten':row['clauses']=deepcopy(rows[0]['clauses'])
    else:row['candidate_id']+='-nested'
    with pytest.raises(ValueError):c.validate_document(row,a)


@pytest.fixture(scope='module')
def frozen(tmp_path_factory):
    pin=c.freeze(tmp_path_factory.mktemp('heading-corpus')/'corpus')
    return pin,json.loads(Path(pin['path']).read_bytes())


def test_training_loader_masks_inventory_admission_and_zero_current_sealed_reads(frozen,monkeypatch):
    pin,m=frozen;blocked={Path(m['artifacts'][k]['path']).resolve() for k in c.SEALED};opened=[];original=Path.open
    def guard(path,*args,**kwargs):
        p=path.resolve();opened.append(p);assert p not in blocked,'current sealed reference read'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',guard)
    loaded=c.load_training_inputs(pin['path'])
    assert len(loaded['boundary_training'])==len(loaded['training_token_roles'])==720
    assert len(loaded['supported_replay'])==528 and len(loaded['supported_heading'])==192
    assert sum(map(len,loaded['replay'].values()))+len(loaded['new_train'])==1152
    assert len(loaded['tuning'])==20 and sum(map(len,loaded['tuning'].values()))==2160
    assert len(loaded['fresh_sources'])==192 and not blocked&set(opened)


@pytest.mark.parametrize('mutation',['inflated_heading','missing_negative','wrong_endpoint','unsupported_mask','retention_drop','source_label'])
def test_loader_rejects_masks_even_after_repaired_hash_or_reference_changes(frozen,tmp_path,mutation):
    _,original=frozen;m=deepcopy(original)
    if mutation=='retention_drop':del m['retention_target_references']['prior_preservation_fresh']
    elif mutation=='source_label':
        rows=c.read_ref(m['artifacts']['fresh_sources']);rows[0]['supported']=True
        m['artifacts']['fresh_sources']=c.write_new(tmp_path/'sources.json',rows)
    else:
        roles=c.read_ref(m['artifacts']['training_token_roles']);role=next(r for r in roles if r['editorial_heading_spans'])
        if mutation=='inflated_heading':role['editorial_heading_spans'][0]['char_end']+=3
        elif mutation=='missing_negative':role['editorial_hard_negative_token_indices'].pop()
        elif mutation=='wrong_endpoint':role['true_end_token_indices'][0]-=1
        else:role['candidate_id']='unsupported-imposter'
        m['artifacts']['training_token_roles']=c.write_new(tmp_path/'roles.json',roles)
    pin=c.write_new(tmp_path/'manifest.json',m)
    with pytest.raises(ValueError):c.load_training_inputs(pin['path'])


def test_old_globals_and_sources_unchanged_and_no_overwrite(frozen):
    pin,_=frozen;before=deepcopy((c.preservation.HEADINGS,c.adapter.make_pair('train',0)))
    c.make_panels();assert before==(c.preservation.HEADINGS,c.adapter.make_pair('train',0))
    with pytest.raises(ValueError,match='new output'):c.freeze(Path(pin['path']).parent)
