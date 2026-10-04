"""Timing attachment ownership, balanced blocks and immutable replay contracts."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts.ops.legal_ir import prepare_legal_timing_ownership_corpus as c


@pytest.fixture(scope='module')
def inventory():return c.make_panels()


def test_all_panels_modality_masks_and_ownership_classes_balance(inventory):
    panels,pairs,blocks,ledger=inventory
    assert {k:len(v) for k,v in panels.items()}==c.COUNTS and len(blocks)==48
    labels={a['id']:a for a in ledger['single_rows']}
    for panel in ('train','tuning','fresh'):
        rows=panels[panel]
        assert Counter((r['canonical_ir']['rules'][0]['modality'],c.presence_mask(r)) for r in rows)=={(m,k):8 for m in 'OPF' for k in range(8)}
        assert Counter(labels[r['id']]['timing_ownership'] for r in rows)=={k:48 for k in c.OWNERSHIP_CLASSES}
        assert Counter(labels[r['id']]['caption_style'] for r in rows)=={k:64 for k in range(3)}
        assert len(pairs[panel])==96


def test_exact_semantic_pair_equality_and_complete_membership(inventory):
    panels,pairs,_,_=inventory
    for panel in ('train','tuning','fresh'):
        c.previous.validate_pairs(panels[panel],pairs[panel],96)
        rows={r['id']:r for r in panels[panel]}
        for p in pairs[panel]:
            left,right=rows[p['left_id']],rows[p['right_id']]
            assert left['canonical_ir']==right['canonical_ir'] and left['source_text']!=right['source_text']


def test_each_new_block_balances_c_e_t_presence(inventory):
    panels,pairs,blocks,_=inventory;rows={r['id']:r for r in panels['train']};pm={p['pair_id']:p for p in pairs['train']}
    seen=[]
    for block in blocks:
        selected=[rows[pm[p][side]] for p in block['pair_ids'] for side in ('left_id','right_id')]
        assert all(sum(bool(r['canonical_ir']['rules'][0][f]) for r in selected)==2 for f in c.FIELDS[3:])
        assert len({r['id'] for r in selected})==4
        seen+=block['pair_ids']
    assert len(seen)==len(set(seen))==96


def test_all_timing_spans_belong_only_to_declared_canonical_facet(inventory):
    panels,_,_,ledger=inventory;rows={r['id']:r for p in ('train','tuning','fresh') for r in panels[p]}
    for a in ledger['single_rows']:
        row=rows[a['id']];c.validate_timing_annotation(row,a)
        for pointer in a['timing_role_spans']:
            span=row['facet_spans'][pointer['owner']]
            assert span[0]<=pointer['char_start']<pointer['char_end']<=span[1]
            assert row['source_text'][pointer['char_start']:pointer['char_end']]==pointer['source_text']
        assert len(a['timing_role_spans'])==int(bool(a['presence_mask']&1))+int(bool(a['presence_mask']&4))


def test_condition_only_timing_never_acquires_action_deadline(inventory):
    panels,_,_,ledger=inventory;labels={a['id']:a for a in ledger['single_rows']}
    selected=[r for r in panels['train'] if labels[r['id']]['timing_ownership']=='condition_only']
    assert len(selected)==48
    for row in selected:
        rule=row['canonical_ir']['rules'][0]
        assert rule['conditions'] and not rule['temporal'] and row['facet_spans']['temporal'] is None
        assert 'application was received ' in rule['conditions'][0]
        assert all(p['owner']=='conditions' for p in labels[row['id']]['timing_role_spans'])


def test_both_class_has_distinct_unambiguous_timing_literals(inventory):
    panels,_,_,ledger=inventory;labels={a['id']:a for a in ledger['single_rows']}
    for panel in ('train','tuning','fresh'):
        both=[r for r in panels[panel] if labels[r['id']]['timing_ownership']=='both']
        assert len(both)==48
        for row in both:
            rule=row['canonical_ir']['rules'][0]
            assert rule['temporal'][0] not in rule['conditions'][0]
            assert row['source_text'].count(rule['temporal'][0])==1


def test_day_hour_calendar_forms_and_complete_receipt_origin(inventory):
    panels,_,_,ledger=inventory;labels={a['id']:a for a in ledger['single_rows']}
    for panel in ('train','tuning','fresh'):
        kinds=Counter(labels[r['id']]['temporal_kind'] for r in panels[panel])
        assert kinds=={None:96,'days':32,'hours':32,'calendar':32}
        for row in panels[panel]:
            conditions=row['canonical_ir']['rules'][0]['conditions']
            if conditions and 'within ' in conditions[0]:assert conditions[0].endswith('of publication')


def test_ownership_cues_cross_front_infix_and_trailing_placements(inventory):
    panels,_,_,ledger=inventory;labels={a['id']:a for a in ledger['single_rows']};positions={'conditions':set(),'temporal':set()}
    for row in panels['train']:
        for field in positions:
            span=row['facet_spans'][field]
            if span:
                p=span[0];positions[field].add('front' if p<row['facet_spans']['actor'][0] else 'suffix' if p>row['facet_spans']['object'][1] else 'infix')
    assert positions=={'conditions':{'front','infix','suffix'},'temporal':{'front','infix','suffix'}}
    assert all(labels[r['id']]['family'] in c.FAMILIES for r in panels['train'])


@pytest.mark.parametrize('mutation',['owner','interval','literal','relation','missing'])
def test_wrong_timing_ownership_annotation_rejected(inventory,mutation):
    panels,_,_,ledger=inventory;row=next(r for r in panels['train'] if c.presence_mask(r)==5)
    label=deepcopy(next(a for a in ledger['single_rows'] if a['id']==row['id']))
    if mutation=='owner':next(p for p in label['timing_role_spans'] if p['owner']=='conditions')['owner']='temporal'
    elif mutation=='interval':label['timing_role_spans'][0]['char_start']-=1
    elif mutation=='literal':label['timing_role_spans'][0]['source_text']='before an unknown event'
    elif mutation=='relation':next(p for p in label['timing_role_spans'] if p['owner']=='conditions')['relation']='independent_action_deadline'
    else:label['timing_role_spans'].pop()
    with pytest.raises(ValueError):c.validate_timing_annotation(row,label)


def test_temporal_absence_false_flag_rejected(inventory):
    panels,_,_,ledger=inventory;row=next(r for r in panels['train'] if c.presence_mask(r)==1)
    label=deepcopy(next(a for a in ledger['single_rows'] if a['id']==row['id']));label['timing_ownership']='deadline_only'
    with pytest.raises(ValueError):c.validate_timing_annotation(row,label)


@pytest.mark.parametrize('mutation',['duplicate','noncomplement','extra_key'])
def test_bad_blocks_rejected(inventory,mutation):
    panels,pairs,blocks,_=inventory;bad=deepcopy(blocks)
    if mutation=='duplicate':bad[1]=bad[0]
    elif mutation=='noncomplement':bad[0]['pair_ids'][1]=bad[1]['pair_ids'][0];bad[0]['block_id']='block-'+c.digest(bad[0]['pair_ids'])
    else:bad[0]['timing_class']='gold'
    with pytest.raises(ValueError):c.validate_blocks(panels['train'],pairs['train'],bad,48)


def test_document_scope_contrasts_and_oracle_multiplicity(inventory):
    panels,pairs,_,ledger=inventory
    for panel in ('document_tuning','document_fresh'):
        rows=panels[panel];labels=[a for a in ledger['document_rows'] if a['panel']==panel]
        c.previous.validate_document_pairs(rows,pairs[panel],labels)
        assert Counter(r['supported'] for r in rows)=={True:48,False:48}
        assert Counter(len(r['clauses']) for r in rows if r['supported'])=={2:24,3:24}
        pack=c.previous.oracle_pack(rows,labels)
        assert len(pack['targets'])==120 and len(pack['document_sources'])==48 and len({r['source_text'] for r in pack['targets']})==114
        assert all('provided that' not in r['source_text'] for r in rows)


def test_document_timing_subspans_are_global_and_source_bound(inventory):
    panels,_,_,ledger=inventory;rows={r['candidate_id']:r for p in ('document_tuning','document_fresh') for r in panels[p]}
    for a in ledger['document_rows']:
        row=rows[a['candidate_id']]
        for clause in a['local_clause_coordinates']:
            for timing in clause['timing_role_spans']:
                owner=clause['facet_spans'][timing['owner']]
                assert owner[0]<=timing['char_start']<timing['char_end']<=owner[1]
                assert row['source_text'][timing['char_start']:timing['char_end']]==timing['source_text']


def test_document_timing_label_tampering_rejected(inventory):
    panels,_,_,ledger=inventory;labels=deepcopy([a for a in ledger['document_rows'] if a['panel']=='document_tuning'])
    coordinate=next(c for a in labels for c in a['local_clause_coordinates'] if c['timing_role_spans'])
    coordinate['timing_role_spans'][0]['char_end']+=1
    with pytest.raises(ValueError):c.validate_document_timing(panels['document_tuning'],labels)


def test_source_case_meaning_isolation_with_shared_templates(inventory):
    panels,pairs,blocks,ledger=inventory;result=c.validate_panels(panels,pairs,blocks,ledger)
    assert result['case_groups']==384 and not result['structural_novelty_claimed']
    train={c.temporal.role_layout(r) for r in panels['train']}
    assert all(c.temporal.role_layout(r) in train for r in panels['fresh'])
    assert all(r['id']=='timing-'+c.sha(r['source_text'].encode()) for r in panels['fresh'])


def test_deterministic_output(inventory):assert c.make_panels()==inventory


def test_fresh_semantic_and_oracle_phase_seals_preserved():
    import inspect
    assert len(c.SEALED)==7 and len(c.EVALUATION_ONLY)==4
    assert 'fresh_oracle_' not in inspect.getsource(c.load_training_inputs)


def test_combined_auxiliary_is_exact_old_prefix_and_under_cap(inventory):
    panels,pairs,blocks,_=inventory
    oldrows,oldlabels,oldpairs=c.previous.make_panel('train');oldblocks=c.previous.make_blocks(oldrows,oldpairs,oldlabels)
    joined=oldrows+panels['train'];joinedpairs=oldpairs+pairs['train'];joinedblocks=oldblocks+blocks
    assert len(joined)==768<=1024 and joined[:576]==oldrows
    c.previous.validate_pairs(joined,joinedpairs,384);c.validate_blocks(joined,joinedpairs,joinedblocks,192)
    assert not {r['source_text'] for r in oldrows}&{r['source_text'] for r in panels['train']}
