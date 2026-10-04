"""Exact owner-coordinate, full denominator and independent interval oracles."""
from copy import deepcopy
import hashlib
import math
import random
import re

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_pointer_metrics_v2 as m


def source(text='Office files before Monday and Office files again.', time='before Monday', query_id='q'):
    a=text.index(time)
    return {'id':query_id,'source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span':{'char_start':a,'char_end':a+len(time)}}


def anchor(s,text,occurrence=0):
    starts=[v.start() for v in re.finditer(re.escape(text),s['source_text'])]
    a=starts[occurrence];return {'char_start':a,'char_end':a+len(text)}


def enumerate_oracle(s,starts,ends):
    tokens=list(re.finditer(r'\w+|[^\w\s]',s['source_text']))
    time=s['proposed_time_span'];values=[]
    for i in range(len(tokens)):
        for j in range(i,len(tokens)):
            if tokens[j].end()<=time['char_start'] or tokens[i].start()>=time['char_end']:
                values.append(((i,j),starts[i]+ends[j]))
    if not values:return {'valid_span_count':0,'raw_owner_token_span':None,'raw_owner_anchor_span':None,'span_confidence':None}
    best=max(v for _,v in values);pair=next(p for p,v in values if v==best)
    p=1/math.fsum(math.exp(v-best) for _,v in values)
    return {'valid_span_count':len(values),'raw_owner_token_span':list(pair),
            'raw_owner_anchor_span':{'char_start':tokens[pair[0]].start(),'char_end':tokens[pair[1]].end()},'span_confidence':p}


def prediction(s,owner='norm',chosen=None,type_strength=12.,span_strength=12.):
    tokens,time=m.source_tokens(s);n=len(tokens);starts=[-span_strength]*n;ends=[-span_strength]*n
    if chosen is not None:
        a,b=m.anchor_tokens(s,chosen);starts[a]=span_strength;ends[b]=span_strength
    pointer=enumerate_oracle(s,starts,ends)
    logits=[type_strength if c==owner else 0. for c in m.CLASSES];probs=m.types.softmax(logits);conf=probs[m.CLASSES.index(owner)]
    accepted=owner!='ambiguous' and conf>=.8
    reason=None if accepted else 'predicted_ambiguous' if owner=='ambiguous' else 'below_fixed_confidence'
    jr=('predicted_ambiguous' if owner=='ambiguous' else 'no_valid_owner_span' if pointer['valid_span_count']==0 else
        'below_fixed_type_confidence' if conf<.8 else 'below_fixed_span_confidence' if pointer['span_confidence']<.8 else None)
    return {'id':s['id'],'source_sha256':s['source_sha256'],'proposed_time_span':s['proposed_time_span'],
        'time_token_span':time,'logits':logits,'probabilities':probs,'predicted_label':owner,'confidence':conf,
        'status':'accepted' if accepted else 'deferred','owner_type':owner if accepted else None,'reason':reason,
        **{k:False for k in m.types.FALSE_FIELDS},'pointer_start_logits':starts,'pointer_end_logits':ends,**pointer,
        'joint_status':'accepted' if jr is None else 'deferred','joint_reason':jr,
        'proposed_owner_anchor_span':pointer['raw_owner_anchor_span'] if jr is None else None}


def test_exhaustive_syntactic_inventory_contains_both_repeated_anchors():
    s=source();first=anchor(s,'Office files',0);second=anchor(s,'Office files',1)
    pairs=m.valid_token_intervals(s)
    assert tuple(m.anchor_tokens(s,first)) in pairs and tuple(m.anchor_tokens(s,second)) in pairs
    assert first!=second
    tokens,time=m.source_tokens(s)
    assert len(pairs)==time[0]*(time[0]+1)//2+(len(tokens)-time[1]-1)*(len(tokens)-time[1])//2


def test_prefix_partition_matches_independent_exhaustive_tiny_span_oracle():
    rng=random.Random(340105)
    for n in range(1,11):
        text=' '.join(f'w{i}' for i in range(n));tokens=list(re.finditer(r'\w+',text))
        for _ in range(20):
            a=rng.randrange(n);b=rng.randrange(a,n);s=source(text,text[tokens[a].start():tokens[b].end()])
            starts=[rng.uniform(-30,30) for _ in range(n)];ends=[rng.uniform(-30,30) for _ in range(n)]
            expected=enumerate_oracle(s,starts,ends);actual=m.span_distribution(s,starts,ends)
            for key in expected:
                if key=='span_confidence' and expected[key] is not None:assert actual[key]==pytest.approx(expected[key],abs=1e-13)
                else:assert actual[key]==expected[key]


def test_invalid_reverse_or_query_crossing_maxima_cannot_evade_normalization():
    s=source('a b c TIME d e f','TIME')
    starts=[-1e6,-1e6,1e6,1e6,-1e6,-1e6,1e6]
    ends=[1e6,-1e6,-1e6,1e6,1e6,-1e6,-1e6]
    a=m.span_distribution(s,starts,ends);b=enumerate_oracle(s,starts,ends)
    assert a['raw_owner_token_span']==b['raw_owner_token_span']
    assert a['span_confidence']==pytest.approx(b['span_confidence'],abs=2e-10)
    assert a['valid_span_count']==12


def test_argmax_ties_are_lexicographic_and_probability_uses_every_valid_pair():
    s=source('a b TIME c d','TIME');p=m.span_distribution(s,[0.]*5,[0.]*5)
    assert p['raw_owner_token_span']==[0,0] and p['valid_span_count']==6
    assert p['span_confidence']==pytest.approx(1/6)


def test_source_containing_only_query_has_no_pointer_and_defer_reason():
    s=source('before Monday','before Monday');p=prediction(s)
    checked=m.checked_prediction(s,p)
    assert checked['accepted_joint'] is False and p['joint_reason']=='no_valid_owner_span'
    assert p['raw_owner_anchor_span'] is p['span_confidence'] is None


@pytest.mark.parametrize('mutation',[
    lambda s:s.update(extra_reference_candidates=[]),
    lambda s:s.update(source_sha256='0'*64),
    lambda s:s['proposed_time_span'].update(char_start=True),
])
def test_source_input_cannot_contain_gold_or_changed_identity(mutation):
    s=source();mutation(s)
    with pytest.raises(ValueError):m.valid_token_intervals(s)


@pytest.mark.parametrize('value',[
    {'char_start':1,'char_end':3}, {'char_start':True,'char_end':6},
    {'char_start':0,'char_end':6,'text':'Office'}, {'char_start':0,'char_end':9999},
])
def test_anchor_must_preserve_exact_closed_integer_token_coordinates(value):
    with pytest.raises(ValueError):m.anchor_tokens(source(),value)


def test_anchor_cannot_cover_or_cross_query_and_source_never_truncated():
    s=source();a=anchor(s,'files before Monday and')
    with pytest.raises(ValueError):m.anchor_tokens(s,a)
    with pytest.raises(ValueError,match='truncation'):m.source_tokens(source(' '.join(['word']*257),'word'))


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(valid_span_count=True),
    lambda p:p.update(raw_owner_token_span=[6,7]),
    lambda p:p['raw_owner_anchor_span'].update(char_start=1),
    lambda p:p.update(span_confidence=.5),
    lambda p:p.update(joint_status='deferred'),
    lambda p:p.update(joint_reason='reviewed'),
    lambda p:p.update(owner_occurrence_resolved=True),
    lambda p:p.update(semantic_candidate_inventory=[]),
    lambda p:p['pointer_start_logits'].pop(),
    lambda p:p['pointer_end_logits'].__setitem__(0,float('nan')),
])
def test_changed_outputs_or_authority_flags_rejected(mutation):
    s=source();p=prediction(s,chosen=anchor(s,'Office files'));mutation(p)
    with pytest.raises(ValueError):m.checked_prediction(s,p)


@pytest.mark.parametrize('case',['type','span','ambiguous'])
def test_both_confidence_thresholds_and_ambiguity_are_independently_required(case):
    s=source();p=prediction(s,owner='ambiguous' if case=='ambiguous' else 'norm',chosen=anchor(s,'Office files'),
        type_strength=1. if case=='type' else 12.,span_strength=0. if case=='span' else 12.)
    result=m.checked_prediction(s,p)
    assert not result['accepted_joint'] and p['proposed_owner_anchor_span'] is None
    assert (p['status']=='accepted') is (case=='span')


def test_wrong_repeated_anchor_is_an_error_even_with_correct_type():
    s=source();p=prediction(s,chosen=anchor(s,'Office files',0));target={'label':'norm','owner_anchor_span':anchor(s,'Office files',1)}
    result=m.score([s],[p],{'q':target})
    assert result['type_correct']==1 and result['anchor_exact']==result['joint_correct']==0
    assert result['accepted_joint_errors']==result['accepted_wrong_anchor_same_type']==1


def test_ambiguity_cannot_be_scored_correct_by_selecting_one_reference_alternative():
    s=source();p=prediction(s,chosen=anchor(s,'Office files'))
    result=m.score([s],[p],{'q':{'label':'ambiguous','owner_anchor_span':None}})
    assert result['ambiguous_joint_acceptances']==result['accepted_joint_errors']==1
    assert result['joint_correct']==0 and result['mean_start_nll_unique']==result['mean_end_nll_unique']==0


def test_all_defer_does_not_hide_determinate_denominator_or_create_coverage():
    sources=[source(query_id='a'),source('Agency files before Tuesday.', 'before Tuesday','b')]
    predictions=[prediction(s,owner='ambiguous') for s in sources]
    targets={'a':{'label':'norm','owner_anchor_span':anchor(sources[0],'Office files')},
             'b':{'label':'ambiguous','owner_anchor_span':None}}
    result=m.score(sources,predictions,targets)
    assert result['count']==2 and result['unique_owner_queries']==result['ambiguous_queries']==1
    assert result['joint_correct']==1 and result['accepted_joint']==0 and result['joint_coverage']==0
    assert result['determinate_deferred']==1 and result['selective_joint_error_rate'] is None


def test_composite_nll_uses_individual_query_masked_endpoints_not_joint_partition():
    s=source('A B TIME C D','TIME');p=prediction(s,chosen=None,type_strength=0.,span_strength=0.)
    result=m.score([s],[p],{'q':{'label':'norm','owner_anchor_span':anchor(s,'A B')}})
    assert result['mean_start_nll_unique']==pytest.approx(math.log(4))
    assert result['composite_nll']==pytest.approx(math.log(4)+math.log(4))
    assert result['composite_nll']!=pytest.approx(math.log(4)+math.log(6))


def test_source_target_join_is_full_and_unique_despite_interval_key_order():
    s=source();p=prediction(s,chosen=anchor(s,'Office files'));target={'label':'norm','owner_anchor_span':anchor(s,'Office files')}
    with pytest.raises(ValueError):m.score([s],[p],{})
    second=deepcopy(s);second['id']='other';second['proposed_time_span']=dict(reversed(list(s['proposed_time_span'].items())))
    other=deepcopy(p);other['id']='other'
    with pytest.raises(ValueError,match='duplicate'):m.score([s,second],[p,other],{'q':target,'other':target})


@pytest.mark.parametrize('label,owner',[('ambiguous',{'char_start':0,'char_end':6}),('norm',None)])
def test_ambiguity_and_unique_owner_reference_contract_cannot_be_swapped(label,owner):
    with pytest.raises(ValueError):m.validate_target(source(),{'label':label,'owner_anchor_span':owner})


def test_pair_addition_rounding_preserves_first_lexicographic_maximum():
    row = source('alpha beta before Monday', 'before Monday')
    starts = [0., 1e-15, 0., 0.]
    ends = [-1e6, 1e6, 0., 0.]
    actual = m.span_distribution(row, starts, ends)
    expected = enumerate_oracle(row, starts, ends)
    assert actual['raw_owner_token_span'] == expected['raw_owner_token_span'] == [0, 1]
    assert actual['span_confidence'] == pytest.approx(expected['span_confidence'], abs=2e-10)
