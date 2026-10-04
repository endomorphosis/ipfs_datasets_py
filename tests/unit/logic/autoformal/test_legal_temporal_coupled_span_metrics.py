"""Independent exhaustive score/loss oracles on fictional source arrays."""
from copy import deepcopy
import math
import random
import re
import pytest
from ipfs_datasets_py.logic.autoformal import legal_temporal_coupled_span_metrics as m
from tests.unit.logic.autoformal.test_legal_temporal_owner_pointer_metrics_v2 import source, prediction


def oracle(s,starts,ends,left,right,enabled=True):
    tokens=list(re.finditer(r'\w+|[^\w\s]',s['source_text']));time=s['proposed_time_span'];pairs=[];scores=[]
    for i in range(len(tokens)):
        for j in range(i,len(tokens)):
            if tokens[j].end()<=time['char_start'] or tokens[i].start()>=time['char_end']:
                pairs.append((i,j));base=float(starts[i])+float(ends[j])
                scores.append(base+math.fsum(float(left[i][k])*float(right[j][k]) for k in range(8))*(1/math.sqrt(8)) if enabled else base)
    if not pairs:return pairs,scores,None,None
    best=max(range(len(scores)),key=scores.__getitem__)
    return pairs,scores,pairs[best],1/math.fsum(math.exp(v-scores[best]) for v in scores)


def zeros(n):return [[0.]*8 for _ in range(n)]


def new_prediction(s,starts=None,ends=None,left=None,right=None,enabled=True):
    row=prediction(s);n=len(row['pointer_start_logits'])
    starts=row['pointer_start_logits'] if starts is None else starts;ends=row['pointer_end_logits'] if ends is None else ends
    left=zeros(n) if left is None else left;right=zeros(n) if right is None else right
    pairs,scores,best,confidence=oracle(s,starts,ends,left,right,enabled)
    tokens=list(re.finditer(r'\w+|[^\w\s]',s['source_text']))
    anchor=None if best is None else {'char_start':tokens[best[0]].start(),'char_end':tokens[best[1]].end()}
    reason=('predicted_ambiguous' if row['predicted_label']=='ambiguous' else 'no_valid_owner_span' if best is None else
            'below_fixed_type_confidence' if row['confidence']<.8 else 'below_fixed_span_confidence' if confidence<.8 else None)
    row.update(pointer_start_logits=starts,pointer_end_logits=ends,pointer_start_factors=left,pointer_end_factors=right,
               interaction_scale=1/math.sqrt(8),interaction_enabled=enabled,valid_span_count=len(pairs),
               raw_owner_token_span=None if best is None else list(best),raw_owner_anchor_span=anchor,span_confidence=confidence,
               joint_reason=reason,joint_status='accepted' if reason is None else 'deferred',proposed_owner_anchor_span=anchor if reason is None else None)
    return row


def test_float64_vector_partition_matches_exhaustive_120_small_sources():
    rng=random.Random(44509)
    for n in range(2,14):
        for _ in range(10):
            text=' '.join('w'+str(i) for i in range(n));s=source(text,'w'+str(rng.randrange(n)))
            starts=[rng.uniform(-15,15) for _ in range(n)];ends=[rng.uniform(-15,15) for _ in range(n)]
            left=[[rng.uniform(-3,3) for _ in range(8)] for _ in range(n)]
            right=[[rng.uniform(-3,3) for _ in range(8)] for _ in range(n)]
            pairs,scores,best,p=oracle(s,starts,ends,left,right)
            actual=m.pair_distribution(s,starts,ends,left,right,enabled=True,scale=m.INTERACTION_SCALE)
            assert actual['pairs']==pairs and actual['best_pair']==best
            assert actual['scores']==pytest.approx(scores,abs=3e-13)
            assert actual['span_confidence']==pytest.approx(p,abs=3e-13)


def test_joint_pair_interaction_changes_owner_without_changing_endpoint_logits():
    s=source('alpha beta before Monday gamma delta','before Monday');n=6
    left=zeros(n);right=zeros(n);left[4][0]=8.;right[5][0]=8.
    row=new_prediction(s,[0.]*n,[0.]*n,left,right)
    result=m.checked_prediction(s,row)
    assert row['raw_owner_token_span']==[4,5] and result['accepted_joint']
    assert m.previous.span_distribution(s,[0.]*n,[0.]*n)['raw_owner_token_span']==[0,0]


def test_query_crossing_interaction_cannot_become_an_owner():
    s=source('alpha beta before Monday gamma delta','before Monday');n=6
    left=zeros(n);right=zeros(n);left[0][0]=100.;right[5][0]=100.
    row=new_prediction(s,[0.]*n,[0.]*n,left,right);m.checked_prediction(s,row)
    assert row['raw_owner_token_span']==[0,0] and row['valid_span_count']==6


def test_disabled_interaction_ignores_large_factors_and_preserves_old_distribution():
    s=source();old=prediction(s);n=len(old['pointer_start_logits'])
    row=new_prediction(s,left=[[1e6]*8 for _ in range(n)],right=[[-1e6]*8 for _ in range(n)],enabled=False)
    result=m.checked_prediction(s,row)
    for key in ('raw_owner_token_span','raw_owner_anchor_span','valid_span_count','span_confidence'):assert row[key]==old[key]
    assert result['distribution']['scalar_fallback'] is False


def test_large_canceling_factors_use_declared_scalar_fsum_fallback():
    s=source('alpha beta before Monday','before Monday');n=4
    left=[[1e6]*8 for _ in range(n)];right=[[(-1.)**k*1e6 for k in range(8)] for _ in range(n)]
    table=m.pair_distribution(s,[0.]*n,[0.]*n,left,right,enabled=True,scale=m.INTERACTION_SCALE)
    assert table['scalar_fallback'] and table['best_pair']==(0,0)
    assert table['scores']==oracle(s,[0.]*n,[0.]*n,left,right)[1]


def test_rounded_endpoint_sum_tie_remains_lexicographically_first():
    s=source('alpha beta before Monday','before Monday');n=4
    row=new_prediction(s,[0.,1e-15,0.,0.],[-1e6,1e6,0.,0.],zeros(n),zeros(n))
    m.checked_prediction(s,row);assert row['raw_owner_token_span']==[0,1]


@pytest.mark.parametrize('mutation',[lambda p:p.update(interaction_enabled=1),lambda p:p.update(interaction_scale=.5),
    lambda p:p['pointer_start_factors'].pop(),lambda p:p['pointer_end_factors'][0].pop(),
    lambda p:p['pointer_start_factors'][0].__setitem__(0,float('nan')),
    lambda p:p['pointer_start_factors'][0].__setitem__(0,True),
    lambda p:p.update(span_confidence=.123),lambda p:p.update(valid_span_count=True),
    lambda p:p.update(raw_owner_token_span=[1,1]),lambda p:p.update(reference_owner_candidates=[])])
def test_closed_factor_and_prediction_contract_rejects_tampering(mutation):
    s=source();row=new_prediction(s);mutation(row)
    with pytest.raises(ValueError):m.checked_prediction(s,row)


def training_fixture(label='norm'):
    s=source('alpha beta before Monday gamma delta','before Monday');n=6
    target={'label':label,'owner_anchor_span':None if label=='ambiguous' else {'char_start':0,'char_end':10}}
    negative={'char_start':25,'char_end':36}
    # Derive exact second phrase coordinates without any semantic proposer.
    negative={'char_start':s['source_text'].index('gamma'),'char_end':len(s['source_text'])}
    contrast={s['id']:{'id':s['id'],'source_sha256':s['source_sha256'],'proposed_time_span':s['proposed_time_span'],
                        'negative_owner_spans':[] if label=='ambiguous' else [negative]}}
    return [s],{s['id']:target},[[0.]*4],[[0.]*n],[[0.]*n],[zeros(n)],[zeros(n)],contrast


@pytest.mark.parametrize('arm',m.ARMS)
def test_uniform_training_losses_have_distinct_correct_normalizers(arm):
    value=m.training_oracle(*training_fixture(),arm=arm)
    assert value['type_ce']==pytest.approx(math.log(4))
    assert value['start_ce']==value['end_ce']==pytest.approx(math.log(4))
    assert value['joint_ce']==pytest.approx(math.log(6)) and value['contrast_ce']==pytest.approx(math.log(2))
    expected=math.log(4)+(.5*2*math.log(4) if arm=='endpoint' else .5*math.log(6))+(.25*math.log(2) if arm=='joint_contrast' else 0.)
    assert value['loss']==pytest.approx(expected)
    assert value['valid_token_masks']==[[True,True,False,False,True,True]]
    assert value['gold_owner_token_spans']==[[0,1]] and value['negative_owner_token_spans']==[[[4,5]]]


def test_all_ambiguous_rows_have_zero_pointer_and_contrast_losses():
    value=m.training_oracle(*training_fixture('ambiguous'),arm='joint_contrast')
    assert value['loss']==value['type_ce']==pytest.approx(math.log(4))
    assert value['unique_count']==value['contrast_count']==0
    assert value['start_ce']==value['end_ce']==value['joint_ce']==value['contrast_ce']==0


def test_no_other_owner_excludes_row_from_contrast_mean():
    args=list(training_fixture());args[-1]['q']['negative_owner_spans']=[]
    value=m.training_oracle(*args,arm='joint_contrast')
    assert value['contrast_count']==0 and value['contrast_ce']==0


@pytest.mark.parametrize('mutation',[lambda c:c.update(source_sha256='0'*64),lambda c:c.update(proposed_time_span={'char_start':0,'char_end':1}),
    lambda c:c.update(negative_owner_spans=[{'char_start':0,'char_end':10}]),
    lambda c:c.update(negative_owner_spans=[{'char_start':11,'char_end':24}]),
    lambda c:c['negative_owner_spans'].append(deepcopy(c['negative_owner_spans'][0])),lambda c:c.update(gold_hint='norm')])
def test_training_contrast_coordinates_and_provenance_fail_closed(mutation):
    args=list(training_fixture());mutation(args[-1]['q'])
    with pytest.raises(ValueError):m.training_oracle(*args,arm='joint_contrast')


def test_parent_and_zero_interaction_common_selection_nll_agree():
    s=source();old=prediction(s);new=new_prediction(s)
    targets={s['id']:{'label':'norm','owner_anchor_span':old['raw_owner_anchor_span']}}
    a=m.score([s],[old],targets);b=m.score([s],[new],targets)
    assert a['selection_nll']==pytest.approx(b['selection_nll'],abs=1e-12)
    assert a['anchor_exact']==b['anchor_exact']==1 and a['joint_correct']==b['joint_correct']==1
    assert a['selection_nll']==a['mean_type_nll']+a['mean_joint_span_nll_unique']


def test_empty_syntactic_inventory_preserves_ambiguity_defer():
    s=source('before Monday','before Monday');row=new_prediction(s,[0.,0.],[0.,0.],zeros(2),zeros(2))
    result=m.checked_prediction(s,row)
    assert row['valid_span_count']==0 and row['span_confidence'] is None and not result['accepted_joint']


@pytest.mark.parametrize('arm',m.ARMS)
def test_float64_runtime_loss_and_gradients_match_independent_stored_array_oracle(arm):
    # Numerical objective evaluation only: no model construction or inference.
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_coupled_span as runtime
    rng=random.Random(7133)
    sources=[];targets={};contrasts={};records=[]
    for index,label in enumerate(('norm','condition','exception','ambiguous')):
        args=training_fixture(label);s=deepcopy(args[0][0]);s['id']=f'fiction-{index}'
        sources.append(s);targets[s['id']]=args[1]['q'];contrasts[s['id']]=deepcopy(args[-1]['q']);contrasts[s['id']]['id']=s['id']
        if index==1:contrasts[s['id']]['negative_owner_spans']=[]
        records.append({'label':index,'tokens':['x']*6,'time_tokens':(2,3),
                        'owner_tokens':None if index==3 else (0,1),
                        'negative_owner_tokens':[(4,5)] if index in (0,2) else []})
    columns=[[[rng.uniform(-2,2) for _ in range(4)] for _ in sources],
             [[rng.uniform(-2,2) for _ in range(6)] for _ in sources],
             [[rng.uniform(-2,2) for _ in range(6)] for _ in sources],
             [[[rng.uniform(-1,1) for _ in range(8)] for _ in range(6)] for _ in sources],
             [[[rng.uniform(-1,1) for _ in range(8)] for _ in range(6)] for _ in sources]]
    tensors=[torch.tensor(v,dtype=torch.float64,requires_grad=True) for v in columns]
    loss,parts=runtime.objective(torch,*tensors,records,arm);loss.backward()
    expected=m.training_oracle(sources,targets,*columns,contrasts,arm=arm)
    for key in parts:
        if type(parts[key]) is float:assert parts[key]==pytest.approx(expected[key],abs=2e-12)
        else:assert parts[key]==expected[key]
    # Check type, eligible endpoints, masked query endpoints, ambiguous endpoints,
    # and each bilinear factor against finite differences of the separate oracle.
    for col,coord in ((0,(2,1)),(1,(0,0)),(1,(0,2)),(2,(3,0)),(3,(0,0,2)),(4,(0,1,2))):
        varied=deepcopy(columns);container=varied[col]
        for v in coord[:-1]:container=container[v]
        original=container[coord[-1]];delta=1e-5
        container[coord[-1]]=original+delta;high=m.training_oracle(sources,targets,*varied,contrasts,arm=arm)['loss']
        container[coord[-1]]=original-delta;low=m.training_oracle(sources,targets,*varied,contrasts,arm=arm)['loss']
        gradient=tensors[col].grad
        actual=0. if gradient is None else float(gradient[coord])
        assert actual==pytest.approx((high-low)/(2*delta),abs=2e-9)
    assert expected['unique_count']==3 and expected['contrast_count']==2
    assert expected['contrast_negative_counts']==[1,0,1,0]


def test_training_contrast_requires_canonical_source_order():
    args=list(training_fixture());s=args[0][0];text=s['source_text']
    args[-1]['q']['negative_owner_spans']=[{'char_start':text.index('delta'),'char_end':len(text)},
                                         {'char_start':text.index('gamma'),'char_end':text.index('gamma')+5}]
    with pytest.raises(ValueError):m.training_oracle(*args,arm='joint_contrast')
