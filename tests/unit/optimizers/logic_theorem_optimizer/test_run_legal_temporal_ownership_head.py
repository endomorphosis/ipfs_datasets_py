"""Selection, source-only generation and full-denominator owner-type metrics."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import pytest
from scripts.ops.legal_ir import run_legal_temporal_ownership_head as runner


def target(label,ordinal=0):
    text=f'Registry{ordinal} shall file within 3 days.';start=text.index('within')
    return {'id':f'q{ordinal}','source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span':{'char_start':start,'char_end':start+13},'label':label,'group_id':'g'}


def predicted(t,p):
    i=max(range(4),key=lambda x:p[x]);accepted=i!=3 and p[i]>=.8
    return {'id':t['id'],'source_sha256':t['source_sha256'],'proposed_time_span':t['proposed_time_span'],
            'logits':[math.log(x) for x in p],'probabilities':p,'predicted_label':runner.runtime.CLASSES[i],
            'confidence':p[i],'status':'accepted' if accepted else 'deferred','owner_type':runner.runtime.CLASSES[i] if accepted else None}


def test_perfect_four_class_model_keeps_ambiguous_in_denominator():
    targets=[target(label,i) for i,label in enumerate(runner.runtime.CLASSES)]
    rows=[predicted(t,[.97 if i==j else .01 for i in range(4)]) for j,t in enumerate(targets)]
    score=runner.metrics(rows,targets)
    assert score['count']==score['correct']==4 and score['macro_f1']==1
    assert score['accepted']==3 and score['deferred']==1 and score['coverage']==.75
    assert score['selective_risk']==0 and score['ambiguous_confident_errors']==0
    assert abs(score['nll']+math.log(.97))<1e-12
    assert abs(score['brier']-(.03**2+3*.01**2))<1e-12
    assert abs(score['ece_10']-.03)<1e-12


def test_always_norm_is_not_rewarded_for_coverage_or_ambiguity():
    targets=[target(label,i) for i,label in enumerate(runner.runtime.CLASSES)]
    score=runner.metrics([predicted(t,[.97,.01,.01,.01]) for t in targets],targets)
    assert score['correct']==1 and score['macro_f1']==.1 and score['coverage']==1
    assert score['accepted_wrong']==3 and score['selective_risk']==.75 and score['ambiguous_confident_errors']==1


def test_all_defer_reports_zero_coverage_and_no_defined_selective_risk():
    targets=[target(label,i) for i,label in enumerate(runner.runtime.CLASSES)]
    score=runner.metrics([predicted(t,[.25]*4) for t in targets],targets)
    assert score['accepted']==0 and score['coverage']==0 and score['selective_risk'] is None
    assert score['count']==4 and score['correct']==1 and score['ambiguous_support']==1


@pytest.mark.parametrize('mutation',['missing','duplicate','id','source','span','nan','probability','status','owner','confidence','class'])
def test_closed_occurrence_scoring_bindings_and_decisions(mutation):
    targets=[target(label,i) for i,label in enumerate(runner.runtime.CLASSES)]
    rows=[predicted(t,[.97,.01,.01,.01]) for t in targets]
    if mutation=='missing':rows.pop()
    if mutation=='duplicate':rows[-1]=deepcopy(rows[0])
    if mutation=='id':rows[0]['id']='unknown'
    if mutation=='source':rows[0]['source_sha256']='0'*64
    if mutation=='span':rows[0]['proposed_time_span']={'char_start':0,'char_end':1}
    if mutation=='nan':rows[0]['logits'][0]=float('nan')
    if mutation=='probability':rows[0]['probabilities']=[.1]*4
    if mutation=='status':rows[0]['status']='deferred'
    if mutation=='owner':rows[0]['owner_type']='condition'
    if mutation=='confidence':rows[0]['confidence']=.5
    if mutation=='class':rows[0]['predicted_label']='condition'
    with pytest.raises(ValueError):runner.metrics(rows,targets)


@pytest.mark.parametrize('scores,expected',[
    ([(.6,.2),(.7,.5),(.65,.1)],100),
    ([(.7,.3),(.7,.2),(.7,.1)],200),
    ([(.7,.2),(.7,.2),(.7,.2)],50),
])
def test_preregistered_rank_only_uses_tuning_macroF1_NLL_earlier(scores,expected):
    stages=[{'steps':step,'tuning_metrics':{'macro_f1':f1,'nll':nll},'fresh_accuracy':100-step}
            for step,(f1,nll) in zip(runner.STAGES,scores)]
    assert runner.select_stage(stages)['steps']==expected
    for stage in stages:stage['fresh_accuracy']=1e9
    assert runner.select_stage(stages)['steps']==expected


def test_incomplete_stage_inventory_is_not_a_valid_selection():
    with pytest.raises(ValueError):runner.select_stage([{'steps':50,'tuning_metrics':{'macro_f1':.7,'nll':.2}}])


def test_authenticated_read_checks_hash_and_optional_byte_count(tmp_path):
    pin=runner.write(tmp_path/'a.json',{'k':1})
    assert runner.read(pin)=={'k':1}
    assert runner.read({**pin,'schema':'metadata'})=={'k':1}
    with pytest.raises(ValueError):runner.read({**pin,'sha256':'0'*64})
    with pytest.raises(ValueError):runner.read({**pin,'bytes':0})
    with pytest.raises(FileExistsError):runner.write(tmp_path/'a.json',{})


def test_source_generation_has_no_target_or_group_inputs_and_actual_counters(tmp_path,monkeypatch):
    targets=[target(label,i) for i,label in enumerate(runner.runtime.CLASSES)]
    sources=runner.runtime.source_queries(targets);source_pin=runner.write(tmp_path/'sources.json',sources)
    cp=runner.write(tmp_path/'checkpoint.json',{})
    monkeypatch.setattr(runner.runtime,'load_checkpoint',lambda *a,**k:{'config':{'arm':'source_only','seed':1730},'optimizer_steps':50})
    class FakeHead:
        def __init__(self,_):self.encoder_batch_forwards=0;self.encoder_source_evaluations=0
        def predict_many(self,queries):
            assert all(set(q)==runner.runtime.SOURCE_KEYS for q in queries)
            self.encoder_batch_forwards+=1;self.encoder_source_evaluations+=len(queries)
            return [predicted(q,[.25]*4) for q in queries]
    monkeypatch.setattr(runner.runtime,'TemporalOwnershipHead',FakeHead)
    pin,value=runner.generate(cp,source_pin,tmp_path/'generation.json')
    assert runner.read(pin)==value and value['sources']==source_pin and value['model']['checkpoint']==cp
    assert value['labels_supplied'] is False and value['time_occurrence_conditioned'] is False
    assert value['encoder_batch_forwards']==1 and value['encoder_source_evaluations']==4
    assert all('label' not in row and 'group_id' not in row for row in value['rows'])


def test_alias_key_includes_both_checkpoint_and_source_manifest():
    a={'checkpoint':'a','sources':'b'}
    assert runner.digest(a)!=runner.digest({**a,'checkpoint':'c'})
    assert runner.digest(a)!=runner.digest({**a,'sources':'c'})


def test_fresh_reference_guard_blocks_all_four_files_before_corpus_load(tmp_path):
    artifacts={}
    for key in runner.SEALED_KEYS:artifacts[key]=runner.write(tmp_path/(key+'.json'),{'secret':key})
    manifest=runner.write(tmp_path/'manifest.json',{'artifacts':artifacts})
    config=runner.write(tmp_path/'config.json',{'corpus_manifest':manifest})
    receipt=runner.install_fresh_reference_guard(config['path'])
    assert len(receipt['sealed_paths'])==4
    for pin in artifacts.values():
        with pytest.raises(PermissionError,match='sealed'):Path(pin['path']).read_bytes()
    assert runner.read(manifest)['artifacts']==artifacts
