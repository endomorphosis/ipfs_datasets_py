"""Independent surface geometry, loss receipts and separate calibration policy."""
from copy import deepcopy
from functools import lru_cache
import math
import random
import re
import pytest
from ipfs_datasets_py.logic.autoformal import legal_temporal_relative_owner_metrics as m
from tests.unit.logic.autoformal.test_legal_temporal_coupled_span_metrics import new_prediction,zeros,training_fixture
from tests.unit.logic.autoformal.test_legal_temporal_owner_pointer_metrics_v2 import source


def relative_prediction(s,base=None,residual=None,enabled=True):
    tokens,_=m.source_tokens(s);n=len(tokens)
    base=[0.]*n if base is None else base;residual=[0.]*n if residual is None else residual
    final=[m.float32(a+b) for a,b in zip(base,residual)]
    row=new_prediction(s,final,final)
    row.update(base_pointer_start_logits=list(base),base_pointer_end_logits=list(base),
               relative_start_logits=list(residual),relative_end_logits=list(residual),relative_enabled=enabled)
    return row


def test_source_geometry_matches_independent_all_token_pair_counting():
    rng=random.Random(9931)
    for n in range(4,32):
        words=[rng.choice(['atom',';',',',':','.','!','?']) for _ in range(n)]
        a=rng.randrange(n-1);words[a:a+2]=['query','timing'];s=source(' '.join(words),'query timing')
        actual=m.source_features(s);den=max(1,n-1);b=a+1
        for i,word in enumerate(words):
            between=[words[k] for k in range(n) if (i<k<a or b<k<i)]
            expected=[(i-a)/den,(i-b)/den,0. if a<=i<=b else min(abs(i-a),abs(i-b))/den,
                float(i<a),float(i>b),float(a<=i<=b),
                *[min(sum(w in group for w in between),4)/4 for group in ({';'},{'.','!','?'},{','},{':'})],
                float(bool(re.fullmatch(r'[^\w\s]',word))),float(word==';')]
            assert actual[i]==expected


def test_surface_geometry_caps_counts_excludes_endpoints_and_is_query_specific():
    s=source('A ; ; ; ; ; before Monday , : ! B before Tuesday ; C','before Monday')
    values=m.source_features(s);tokens,(a,b)=m.source_tokens(s)
    assert values[0][6]==1. and values[1][6]==1.
    assert all(values[i][2]==0. and values[i][5]==1. for i in range(a,b+1))
    next_query=deepcopy(s);start=s['source_text'].index('before Tuesday')
    next_query['proposed_time_span']={'char_start':start,'char_end':start+len('before Tuesday')}
    assert m.source_features(next_query)!=values


def test_geometry_does_not_use_query_id_or_source_owner_label():
    s=source();r=deepcopy(s);r['id']='opaque-renamed-id'
    assert m.source_features(s)==m.source_features(r)


def test_runtime_source_geometry_agrees_without_model_or_neural_call():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_relative_owner as runtime
    s=source('A ; ; : . before Monday, B ? C','before Monday');tokens,time=m.source_tokens(s)
    record={'tokens':[{'text':t.group()} for t in tokens],'time_tokens':time,'label':999,'owner_tokens':None}
    assert runtime.relative_features(record)==m.source_features(s)


def test_relative_residual_changes_argmax_with_exact_float32_addition():
    s=source();n=len(m.source_tokens(s)[0]);base=[m.float32(.1)]*n;residual=[0.]*n;residual[1]=10.
    row=relative_prediction(s,base,residual);m.checked_prediction(s,row)
    assert row['raw_owner_token_span']==[1,1]
    assert row['pointer_start_logits'][1]==m.float32(base[1]+residual[1])


@pytest.mark.parametrize('mutation',[
    lambda r:r['relative_start_logits'].__setitem__(0,.1),
    lambda r:r['base_pointer_end_logits'].pop(),
    lambda r:r.update(relative_enabled=1),
    lambda r:r['pointer_start_logits'].__setitem__(0,m.float32(1e-7)),
    lambda r:r.update(relative_features=[[0.]*12]),
    lambda r:r['relative_end_logits'].__setitem__(0,float('nan')),
    lambda r:r['base_pointer_start_logits'].__setitem__(0,True)])
def test_relative_prediction_wire_and_addition_fail_closed(mutation):
    s=source();row=relative_prediction(s);mutation(row)
    with pytest.raises(ValueError):m.checked_prediction(s,row)


def test_source_pointer_cannot_hide_applied_nonzero_residual():
    s=source();n=len(m.source_tokens(s)[0]);row=relative_prediction(s,residual=[1.]*n,enabled=False)
    with pytest.raises(ValueError,match='zero'):m.checked_prediction(s,row)


@pytest.mark.parametrize('arm',m.ARMS)
def test_norm_only_loss_and_required_saved_column_binding(arm):
    args=list(training_fixture());sources,targets,logits,starts,ends,left,right,contrasts=args
    value=m.training_oracle(*args,arm=arm,base_starts=starts,base_ends=ends,
                           relative_starts=[[0.]*6],relative_ends=[[0.]*6])
    expected=math.log(4)+.5*math.log(6)+(.25*math.log(2) if arm=='relative_norm_contrast' else 0.)
    assert value['loss']==pytest.approx(expected) and value['norm_count']==1
    assert value['interaction_enabled'] is True and value['source_encoder_frozen'] and value['type_head_frozen']
    targets['q']['label']='condition'
    with pytest.raises(ValueError,match='norm'):
        m.training_oracle(*args,arm=arm,base_starts=starts,base_ends=ends,relative_starts=[[0.]*6],relative_ends=[[0.]*6])


@pytest.mark.parametrize('label',['condition','exception','ambiguous'])
def test_non_norm_queries_never_receive_other_action_contrast(label):
    args=list(training_fixture(label));args[-1]['q']['negative_owner_spans']=[]
    value=m.training_oracle(*args,arm='relative_norm_contrast',base_starts=args[3],base_ends=args[4],
                           relative_starts=[[0.]*6],relative_ends=[[0.]*6])
    assert value['norm_count']==value['contrast_count']==0 and value['contrast_ce']==0.


def _with_confidence(s,probability):
    n=len(m.source_tokens(s)[0]);lo,hi=0.,25.
    for _ in range(50):
        amount=(lo+hi)/2;values=[0.]*n;values[1]=amount
        confidence=m.previous.span_distribution(s,values,values)['span_confidence']
        if confidence<probability:lo=amount
        else:hi=amount
    values=[0.]*n;values[1]=m.float32((lo+hi)/2)
    return relative_prediction(s,values)


@lru_cache(maxsize=1)
def calibration_fixture():
    sources={};predictions={};targets={}
    for panel in m.CALIBRATION_PANELS:
        sources[panel]=[];predictions[panel]=[];targets[panel]={}
        for group in range(48):
            text=f'Alpha files before Monday Beta records before Tuesday Gamma publishes before Friday tag {panel}{group}.'
            for query,time in enumerate(('before Monday','before Tuesday','before Friday')):
                s=source(text,time,query_id=f'{panel}-{group}-{query}');r=_with_confidence(s,.97)
                sources[panel].append(s);predictions[panel].append(r)
                targets[panel][s['id']]={'label':'norm','owner_anchor_span':r['raw_owner_anchor_span']}
    return sources,predictions,targets


def fresh_fixture():return deepcopy(calibration_fixture())


def restrict_confidence(args,indices_by_panel):
    sources,predictions,_=args
    for panel in m.CALIBRATION_PANELS:
        for index,s in enumerate(sources[panel]):
            if index not in indices_by_panel[panel]:predictions[panel][index]=_with_confidence(s,.5)


def test_calibration_uses_highest_coverage_zero_error_policy_and_higher_threshold_tie():
    sources,predictions,targets=fresh_fixture();panel=m.CALIBRATION_PANELS[0]
    predictions[panel][0]=_with_confidence(sources[panel][0],.83)
    targets[panel][sources[panel][0]['id']]['owner_anchor_span']={'char_start':0,'char_end':5}
    result=m.calibrate(sources,predictions,targets)
    assert result['policy']['span_threshold']==.95 and result['selected_accepted_queries']==287
    assert result['grid_results'][0]['accepted_joint_errors']==1
    assert result['fresh_results_used'] is False and result['statistical_safety_guarantee'] is False


def test_all_high_confidence_errors_force_explicit_defer_all_not_threshold_one():
    sources,predictions,targets=fresh_fixture()
    for panel in m.CALIBRATION_PANELS:
        predictions[panel][0]=_with_confidence(sources[panel][0],.999)
        targets[panel][sources[panel][0]['id']]['owner_anchor_span']={'char_start':0,'char_end':5}
    result=m.calibrate(sources,predictions,targets)
    assert result['explicit_defer_all_fallback'] and result['policy']['mode']=='accept_none'
    assert result['policy']['span_threshold'] is None
    assert all(v['accepted_joint_errors']==2 for v in result['grid_results'])


def test_minimum_48_query_support_is_not_optional():
    args=fresh_fixture();a,b=m.CALIBRATION_PANELS
    restrict_confidence(args,{a:set(range(0,72,3)),b:set(range(0,69,3))})
    result=m.calibrate(*args)
    assert result['explicit_defer_all_fallback']
    assert result['grid_results'][0]['accepted_joint']==47 and result['grid_results'][0]['accepted_source_count']==47
    assert result['grid_results'][0]['constraints']['minimum_per_panel']


def test_minimum_24_distinct_sources_counts_hashes_not_query_ids():
    args=fresh_fixture();a,b=m.CALIBRATION_PANELS
    restrict_confidence(args,{a:set(range(24)),b:set(range(24))})
    result=m.calibrate(*args)
    assert result['explicit_defer_all_fallback']
    assert result['grid_results'][0]['accepted_joint']==48 and result['grid_results'][0]['accepted_source_count']==16


def test_minimum_12_accepted_queries_per_panel_blocks_one_panel_policy():
    args=fresh_fixture();a,b=m.CALIBRATION_PANELS
    restrict_confidence(args,{a:set(range(0,111,3)),b:set(range(0,33,3))})
    result=m.calibrate(*args)
    assert result['explicit_defer_all_fallback']
    assert result['grid_results'][0]['accepted_joint']==48 and result['grid_results'][0]['accepted_source_count']==48
    assert not result['grid_results'][0]['constraints']['minimum_per_panel']


def test_exact_support_boundaries_are_eligible():
    args=fresh_fixture();a,b=m.CALIBRATION_PANELS
    restrict_confidence(args,{a:set(range(36)),b:set(range(0,36,3))})
    result=m.calibrate(*args)
    assert not result['explicit_defer_all_fallback'] and result['policy']['span_threshold']==.95
    assert result['selected_accepted_queries']==48
    chosen=[r for r in result['grid_results'] if r['span_threshold']==.95][0]
    assert chosen['accepted_source_count']==24 and chosen['panel_metrics'][b]['accepted_joint']==12


@pytest.mark.parametrize('mutation',[lambda s,p,t:s.pop(m.CALIBRATION_PANELS[0]),
    lambda s,p,t:p[m.CALIBRATION_PANELS[0]].pop(),
    lambda s,p,t:t[m.CALIBRATION_PANELS[0]].pop(next(iter(t[m.CALIBRATION_PANELS[0]]))),
    lambda s,p,t:p[m.CALIBRATION_PANELS[0]][0].update(source_sha256='0'*64)])
def test_calibration_requires_complete_authenticated_source_joins(mutation):
    args=fresh_fixture();mutation(*args)
    with pytest.raises((ValueError,KeyError)):m.calibrate(*args)


@pytest.mark.parametrize('mutation',[lambda p:p.update(span_threshold=1.),lambda p:p.update(type_threshold=.7),
    lambda p:p.update(safety_guarantee=True),lambda p:p['support_requirements'].update(minimum_accepted_queries=1),
    lambda p:p.update(mode='accept_none'),lambda p:p.update(fresh_accuracy=1.)])
def test_policy_cannot_silently_relax_prospective_contract(mutation):
    policy=m._policy(.95);mutation(policy)
    with pytest.raises(ValueError):m.validate_policy(policy)


def test_policy_application_preserves_raw_correctness_and_only_vetoes_acceptance():
    args=fresh_fixture();s,p,t=(v[m.CALIBRATION_PANELS[0]] for v in args)
    raw=m.score(s,p,t);cal=m.apply_policy_score(s,p,t,m._policy(None))
    assert cal['raw_joint_correct']==raw['joint_correct']==144 and cal['raw_anchor_exact']==144
    assert cal['accepted_joint']==0 and cal['accepted_joint_errors']==0
    assert all(r['fixed_accepted_joint'] and not r['calibrated_accepted_joint'] for r in cal['rows'])
    assert all(r['calibrated_joint_reason']=='calibration_accept_none' for r in cal['rows'])


def test_relative_wire_cannot_disable_inherited_rank8_interaction():
    s=source();row=relative_prediction(s);row['interaction_enabled']=False
    with pytest.raises(ValueError,match='interaction'):m.checked_prediction(s,row)


def test_cross_panel_alias_is_not_two_independent_calibration_inventories():
    s,p,t=fresh_fixture();a,b=m.CALIBRATION_PANELS
    s[b]=deepcopy(s[a]);p[b]=deepcopy(p[a]);t[b]=deepcopy(t[a])
    with pytest.raises(ValueError,match='overlap'):m.calibrate(s,p,t)


def test_ambiguous_predictions_defer_despite_high_span_confidence():
    from tests.unit.logic.autoformal.test_legal_temporal_owner_pointer_metrics_v2 import prediction
    s=source();row=relative_prediction(s);row.update({k:v for k,v in prediction(s,owner='ambiguous').items() if k in m.types.PREDICTION_KEYS})
    row.update(joint_status='deferred',joint_reason='predicted_ambiguous',proposed_owner_anchor_span=None)
    result=m.apply_policy_score([s],[row],{s['id']:{'label':'ambiguous','owner_anchor_span':None}},m._policy(.8))
    assert result['accepted_joint']==0 and result['raw_joint_correct']==1


def test_confident_type_prediction_on_authored_ambiguity_counts_as_joint_error():
    s,p,t=fresh_fixture();panel=m.CALIBRATION_PANELS[0];row=s[panel][0]
    p[panel][0]=_with_confidence(row,.999)
    t[panel][row['id']]={'label':'ambiguous','owner_anchor_span':None}
    result=m.calibrate(s,p,t)
    assert result['explicit_defer_all_fallback']
    assert all(v['accepted_joint_errors']==1 for v in result['grid_results'])
