"""Fictional source examples only; no training/evaluation corpus access."""
import copy
import hashlib
import math

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v4 as p
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_eligibility_adapter as a

CHECKPOINT='a'*64


def policy(mode='threshold', threshold=.95):
    return {'schema':a.POLICY_SCHEMA,'checkpoint_sha256':CHECKPOINT,'mode':mode,
            'threshold':threshold if mode=='threshold' else None,'calibration_sha256':'b'*64,
            'selection_rule':a.SELECTION_RULE}


def prediction(query, probability=.99):
    values=[1-probability,probability];index=0 if values[0]>=values[1] else 1
    return {'schema':a.PREDICTION_SCHEMA,'query':copy.deepcopy(query),'checkpoint_sha256':CHECKPOINT,
            'class_order':['defer_surface','eligible_surface'],'logits':[math.log(x) for x in values],
            'probabilities':values,'predicted_label':a.CLASS_ORDER[index],'confidence':values[index],
            'authority':dict(a.PREDICTION_AUTHORITY),'formula_admission':False}


def assessed(text,probability=.99,chosen_policy=None):
    raw=p.propose(text)
    preds=[prediction(r['query'],probability) for r in raw['proposals']]
    return raw,a.assess(text,raw,preds,chosen_policy or policy())


def test_nested_component_blocks_outer_and_inner_but_keeps_punctuated_occurrence():
    text=('Office acts within 6 days of the closure within 2 weeks after issuance of the warrant; '
          'Registry acts after receipt.')
    raw=p.propose(text);before=a.wire(raw);planned=a.plan(text,raw)
    assert len(planned['inventory'])==3
    assert [r['baseline_eligible'] for r in planned['inventory']]==[False,False,True]
    assert [a.NESTED_GUARD in r['hard_block_reasons'] for r in planned['inventory']]==[True,True,False]
    assert len(planned['conflict_components'])==1
    assert planned['conflict_components'][0]['query_ids']==[r['query']['id'] for r in planned['inventory'][:2]]
    assert a.wire(raw)==before
    _,result=assessed(text)
    assert result['counts']['baseline_blocked']==1 and result['counts']['eligible_queries']==1
    assert result['rows'][1]['eligible_probability']==.99
    assert result['rows'][1]['eligible'] is False


def test_transitive_overlapping_nested_envelopes_share_one_component():
    text='Office acts after receipt until approval after completion; Registry acts after delivery.'
    planned=a.plan(text,p.propose(text))
    assert len(planned['inventory'])==4
    assert len(planned['conflict_components'])==1
    assert len(planned['conflict_components'][0]['query_ids'])==3
    assert all(not r['baseline_eligible'] for r in planned['inventory'][:3])
    assert planned['inventory'][3]['baseline_eligible']


def test_separate_identical_occurrences_do_not_conflict():
    text='Office acts after receipt; Registry acts after receipt.'
    planned=a.plan(text,p.propose(text))
    assert planned['conflict_components']==[]
    assert all(r['baseline_eligible'] for r in planned['inventory'])
    assert planned['inventory'][0]['query']['id']!=planned['inventory'][1]['query']['id']


def test_only_sole_unknown_shape_can_be_overridden_without_mutating_raw_receipt():
    text='Office acts within 4 weeks after the archivist authenticates the record.'
    raw=p.propose(text);before=copy.deepcopy(raw);planned=a.plan(text,raw)
    assert planned['inventory'][0]['overridable']
    assert not planned['inventory'][0]['baseline_eligible']
    result=a.assess(text,raw,[prediction(raw['proposals'][0]['query'])],policy())
    assert result['rows'][0]['learned_override'] and result['rows'][0]['eligible']
    assert raw==before and raw['proposals'][0]['status']=='deferred'
    assert result['queries']==[raw['proposals'][0]['query']]
    assert result['rows'][0]['semantic_flags']==raw['proposals'][0]['semantic_flags']
    assert not any(result['authority'].values()) and result['formula_admission'] is False


@pytest.mark.parametrize('text,reason',[
    ('After receipt the Board shall file.','ambiguous_unpunctuated_clause_boundary'),
    ('Office acts after receipt under paragraph (1.','unbalanced_delimiters'),
    ('Office acts after receipt of "the notice.','unterminated_quotation'),
    ('Office acts within 4 days of notice of the hearing.','unsupported_temporal_prefix'),
    ('Caption "within 4 days of notice".','quoted_time_mention'),
])
def test_hard_raw_reasons_cannot_be_overridden(text,reason):
    raw,result=assessed(text)
    assert raw['proposals']
    assert all(not r['eligible'] and not r['overridable'] for r in result['rows'])
    assert reason in result['rows'][0]['hard_block_reasons']
    assert result['queries']==[]


def test_source_delimiter_error_blocks_an_otherwise_eligible_legacy_span():
    text='Office acts within 4 days of notice (unfinished.'
    raw=p.propose(text)
    assert raw['proposals'][0]['status']=='surface_candidate'
    result=a.assess(text,raw)
    assert result['queries']==[]
    assert result['rows'][0]['hard_block_reasons']==['unbalanced_delimiters']


def test_source_token_budget_keeps_inventory_and_blocks_all_overrides():
    text='word '*254+' after receipt.'
    raw,result=assessed(text)
    assert result['counts']['raw_candidates']==1
    assert 'source_token_budget_exceeded' in result['rows'][0]['hard_block_reasons']
    assert result['queries']==[]


def test_source_token_byte_budget_prevents_model_admission():
    text='x'*2050+' after receipt.'
    raw=p.propose(text);result=a.assess(text,raw)
    assert result['counts']['raw_baseline_eligible']==1
    assert result['rows'][0]['hard_block_reasons']==['source_token_byte_budget_exceeded']
    assert result['queries']==[]


def test_accept_none_removes_only_learned_overrides():
    text='Office acts after receipt; Registry acts after the archivist authenticates the record.'
    _,result=assessed(text,chosen_policy=policy('accept_none'))
    assert [r['eligible'] for r in result['rows']]==[True,False]
    assert result['rows'][1]['decision_reason']=='policy_accept_none'


@pytest.mark.parametrize('probability,expected',[(.94,False),(.95,True),(.96,True)])
def test_exact_calibrated_threshold_boundary(probability,expected):
    _,result=assessed('Office acts after the archivist authenticates the record.',probability)
    assert result['rows'][0]['eligible'] is expected


def test_empty_raw_inventory_with_issue_is_preserved():
    text='Office acts within zero days after receipt.'
    raw=p.propose(text);result=a.assess(text,raw,[],policy())
    assert result['rows']==[] and result['queries']==[]
    assert a.plan(text,raw)['issues']==raw['issues']


@pytest.mark.parametrize('mutation',['source','status','reason','offset','semantic','authority','extra','pin'])
def test_raw_receipt_authentication_rejects_mutations(mutation):
    text='Office acts after receipt.';raw=copy.deepcopy(p.propose(text))
    if mutation=='source':raw['source_text']+=' '
    elif mutation=='status':raw['proposals'][0]['status']='deferred'
    elif mutation=='reason':raw['proposals'][0]['reason_codes']=['unsupported_event_shape']
    elif mutation=='offset':raw['proposals'][0]['query']['proposed_time_span']['char_end']-=1
    elif mutation=='semantic':raw['proposals'][0]['semantic_flags']['event_reference_unresolved']=False
    elif mutation=='authority':raw['authority']['owner_assigned']=True
    elif mutation=='extra':raw['owner_label']='norm'
    else:raw['producer_pins'][next(iter(raw['producer_pins']))]='c'*64
    with pytest.raises(ValueError):a.plan(text,raw)


@pytest.mark.parametrize('mutation',['checkpoint','query_id','source','span','class_order','logit_nan','probability',
                                     'confidence','label','authority','formula','extra','missing','duplicate'])
def test_prediction_binding_and_arithmetic_rejects_mutation(mutation):
    text='Office acts after receipt.';raw=p.propose(text);pred=prediction(raw['proposals'][0]['query']);preds=[pred]
    if mutation=='checkpoint':pred['checkpoint_sha256']='c'*64
    elif mutation=='query_id':pred['query']['id']='occ-'+'c'*64
    elif mutation=='source':pred['query']['source_text']+=' '
    elif mutation=='span':pred['query']['proposed_time_span']['char_end']-=1
    elif mutation=='class_order':pred['class_order'].reverse()
    elif mutation=='logit_nan':pred['logits'][0]=float('nan')
    elif mutation=='probability':pred['probabilities']=[.5,.5]
    elif mutation=='confidence':pred['confidence']=.5
    elif mutation=='label':pred['predicted_label']='defer_surface'
    elif mutation=='authority':pred['authority']['owner_assigned']=True
    elif mutation=='formula':pred['formula_admission']=True
    elif mutation=='extra':pred['owner']='norm'
    elif mutation=='missing':preds=[]
    else:preds.append(copy.deepcopy(pred))
    with pytest.raises(ValueError):a.assess(text,raw,preds,policy())


@pytest.mark.parametrize('mutation',['threshold','boolean_threshold','checkpoint','calibration','mode','rule','extra'])
def test_closed_policy_validation(mutation):
    value=policy()
    if mutation=='threshold':value['threshold']=.91
    elif mutation=='boolean_threshold':value['threshold']=True
    elif mutation=='checkpoint':value['checkpoint_sha256']='x'
    elif mutation=='calibration':value['calibration_sha256']=None
    elif mutation=='mode':value['mode']='accept_all'
    elif mutation=='rule':value['selection_rule']='owner-policy'
    else:value['owner_threshold']=.8
    with pytest.raises(ValueError):a.validate_policy(value)


def test_predictions_policy_must_be_supplied_together():
    text='Office acts after receipt.';raw=p.propose(text)
    with pytest.raises(ValueError):a.assess(text,raw,[],None)
    with pytest.raises(ValueError):a.assess(text,raw,None,policy())


def test_first_class_tie_and_no_threshold_confusion():
    text='Office acts after the archivist authenticates the record.';raw=p.propose(text)
    pred=prediction(raw['proposals'][0]['query'],.5)
    assert pred['predicted_label']=='defer_surface'
    result=a.assess(text,raw,[pred],policy())
    assert result['queries']==[]


def test_source_and_policy_receipt_bindings_are_digests_of_complete_wire():
    text='Office acts after receipt.';raw,result=assessed(text)
    assert result['raw_receipt_sha256']==a.digest(raw)
    assert result['plan_sha256']==a.digest(a.plan(text,raw))
    assert result['policy_sha256']==a.digest(result['policy'])
    assert result['checkpoint_sha256']==CHECKPOINT
    assert result['model_calls_by_adapter']==0


def test_pinned_v4_hash_cannot_be_silently_reinterpreted(monkeypatch):
    monkeypatch.setattr(a,'FROZEN_PROPOSER_SHA256','c'*64)
    with pytest.raises(ValueError,match='frozen v4'):a.producer_pins()
