"""Independent release ordering, metric, parent selection and alias contracts."""
from copy import deepcopy
import hashlib
import json

import pytest

from scripts.ops.legal_ir import qualify_legal_paired_ownership_head as q


def selection_scores():
    return {step: {'single_tuning': {'count':144, 'correct':144, 'accepted_type_errors':0, 'macro_f1':1., 'mean_nll':.05},
                   'paired_tuning': {'count':288, 'correct':200, 'accepted_type_errors':8, 'macro_f1':.7, 'mean_nll':.6}}
            for step in q.STEPS}


def test_parent_included_and_tie_prefers_no_updates():
    assert q.independent_selection(selection_scores())['selected_steps'] == 0


def test_new_tuning_rank_and_old_tuning_error_retention_are_independent():
    scores = selection_scores(); scores[50]['paired_tuning']['macro_f1'] = .9
    scores[100]['paired_tuning']['macro_f1'] = .99; scores[100]['single_tuning']['correct'] = 143
    scores[200]['paired_tuning']['macro_f1'] = 1.; scores[200]['single_tuning'].update(correct=143,accepted_type_errors=1)
    result = q.independent_selection(scores)
    assert result['selected_steps'] == 50 and result['eligible_steps'] == [0,50]


def test_nll_then_earliest_stage_tiebreak_and_no_coverage_gate():
    scores = selection_scores()
    for step in (100,200):
        scores[step]['paired_tuning'].update(mean_nll=.5, accepted_type_proposals=0)
    assert q.independent_selection(scores)['selected_steps'] == 100
    assert q.independent_selection(scores)['coverage_gate_applied'] is False


@pytest.mark.parametrize('mutation', [
    lambda s:s.pop(0), lambda s:s.pop(200), lambda s:s.update({True:s[50]}),
    lambda s:s[0]['single_tuning'].update(count=True),
    lambda s:s[50]['single_tuning'].update(correct=145),
    lambda s:s[50]['single_tuning'].update(accepted_type_errors=True),
    lambda s:s[50]['paired_tuning'].update(macro_f1=float('nan')),
    lambda s:s[50]['paired_tuning'].update(macro_f1=2.),
    lambda s:s[50]['paired_tuning'].update(mean_nll=-1.),
])
def test_invalid_selection_counts_rejected(mutation):
    scores = selection_scores(); mutation(scores)
    with pytest.raises(ValueError):q.independent_selection(scores)


def sample():
    text = 'Registry shall file within 7 days of notice.'; a=text.index('within'); b=text.index('.')
    source={'id':'query','source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span':{'char_start':a,'char_end':b}}
    probabilities=q.metric.softmax([4.,0.,0.,0.])
    row={'id':'query','source_sha256':source['source_sha256'],'proposed_time_span':source['proposed_time_span'],
         'time_token_span':q.metric.validate_source(source),'logits':[4.,0.,0.,0.],'probabilities':probabilities,
         'predicted_label':'norm','confidence':probabilities[0],'status':'accepted','owner_type':'norm','reason':None,
         **{k:False for k in q.metric.FALSE_FIELDS}}
    cp={'path':'/checkpoint','bytes':1,'sha256':'a'*64,'schema':q.CHECKPOINT_SCHEMA}
    pin={'path':'/source','bytes':1,'sha256':'b'*64}
    value={'schema':'legal-paired-temporal-owner-type-source-generation/v1','model':{'checkpoint':cp,'arm':'mixed_occurrences','seed':1730,'steps':200},
           'sources':pin,'class_order':list(q.metric.CLASSES),'threshold':.8,'rows':[row],
           'encoder_batch_forwards':1,'encoder_source_evaluations':1,'source_text_conditioned':True,
           'time_occurrence_conditioned':True,'labels_supplied':False,'source_id_used_as_feature':False,'owner_or_cue_spans_supplied':False,
           **{k:False for k in q.metric.FALSE_FIELDS}}
    return source,row,cp,pin,value


def verify_sample(value, source, cp, pin):
    return q.generation(value,cp,pin,[source],arm='mixed_occurrences',seed=1730,step=200)


def test_full_prediction_wire_and_occurrence_are_verified():
    source,row,cp,pin,value=sample()
    assert verify_sample(value,source,cp,pin)==[row]


@pytest.mark.parametrize('mutation', [
    lambda v:v['model'].update(steps=True), lambda v:v['model'].update(arm='single_replay'),
    lambda v:v.update(labels_supplied=True),lambda v:v.update(time_occurrence_conditioned=False),
    lambda v:v.update(owner_or_cue_spans_supplied=True),lambda v:v.update(source_id_used_as_feature=True),
    lambda v:v.update(encoder_batch_forwards=True),lambda v:v.update(rows=[]),
    lambda v:v['rows'][0]['proposed_time_span'].update(char_start=True),
    lambda v:v['rows'][0].update(owner_occurrence_resolved=True),
])
def test_changed_prediction_metadata_rejected(mutation):
    source,_,cp,pin,value=sample();mutation(value)
    with pytest.raises(ValueError):verify_sample(value,source,cp,pin)


def test_typed_checkpoint_reference_exact_schema_and_bytes(tmp_path):
    path=tmp_path/'checkpoint.json';pin=q.write(path,{'schema':q.CHECKPOINT_SCHEMA})
    typed={**pin,'schema':q.CHECKPOINT_SCHEMA};q.read_producer(typed)
    with pytest.raises(ValueError):q.read_producer({**typed,'bytes':True})
    with pytest.raises(ValueError):q.read_producer({**typed,'schema':'wrong'})
    path.write_text('{"schema":"changed"}')
    with pytest.raises(ValueError):q.read_producer(typed)


def test_checkpoint_metadata_schema_must_equal_file(tmp_path):
    pin=q.write(tmp_path/'checkpoint.json',{'schema':'wrong'})
    with pytest.raises(ValueError):q.read({**pin,'schema':q.CHECKPOINT_SCHEMA})


def test_duplicate_json_keys_and_nonfinite_constants_rejected(tmp_path):
    path=tmp_path/'evidence.json';path.write_text('{"x":1,"x":2}')
    with pytest.raises(ValueError):q.read(q.reference(path))
    path.write_text('{"x":NaN}')
    with pytest.raises(ValueError):q.read(q.reference(path))


def test_existing_evidence_never_overwritten(tmp_path):
    p=tmp_path/'evidence.json';q.write(p,{'x':1})
    with pytest.raises(FileExistsError):q.write(p,{'x':2})
    assert json.loads(p.read_text())=={'x':1}


def test_paired_counts_bind_source_occurrence_and_reference():
    source,row,*_=sample();a=q.metric.score([source],[row],{'query':'norm'})
    assert q.paired_comparison(a,a)['correct_delta']==0
    b=deepcopy(a);b['rows'][0]['target']='condition'
    with pytest.raises(ValueError):q.paired_comparison(a,b)


def test_error_retention_rejects_while_accuracy_retained():
    scores=selection_scores()
    for step in q.STEPS:scores[step]['single_tuning']['correct']=143
    scores[50]['paired_tuning']['macro_f1']=.99
    scores[50]['single_tuning']['accepted_type_errors']=1
    assert q.independent_selection(scores)['selected_steps']==0


def test_actual_os_guard_denies_until_explicit_release(tmp_path):
    paths=[tmp_path/f'sealed-{i}.json' for i in range(4)]
    for p in paths:p.write_text('{}')
    manifest={'artifacts':{str(i):q.reference(p) for i,p in enumerate(paths)}}
    state=q.phase_guard(manifest,tuple(manifest['artifacts']))
    with pytest.raises(PermissionError):paths[0].read_text()
    assert state['premature_read_attempts']==[str(paths[0])]
    state['released']=True
    assert paths[1].read_text()=='{}'
    assert state['postrelease_reads']==[str(paths[1])]
    b=deepcopy(a);b['rows'][0]['source_sha256']='0'*64
    with pytest.raises(ValueError):q.paired_comparison(a,b)
