"""Postfit evaluator contracts without model or encoder execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/evaluate_multidimension_modality_holdout.py'
SPEC=importlib.util.spec_from_file_location('_multidimension_modality_holdout_tests',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def test_exact_twelve_panels_on_old_exposed_cohort():
    assert subject.jobs()==[(d,1729,a) for d in (8,384,768) for a in ('source-head-lr10','aux-used113')]
    assert subject.FIXED['panel_count']==len(subject.jobs())*len(subject.ROLES)==12
    assert subject.FIXED['previously_exposed'] and subject.FIXED['fresh_holdout'] is False
    assert subject.FIXED['training_executed'] is subject.FIXED['encoder_executed'] is False


@pytest.mark.parametrize('key,value',[('dimensions',[8,384,768,4096]),('seed_order',[1729,2718]),
    ('panel_count',36),('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),
    ('temperature',1),('teacher_forced_full_vocabulary_size',3),('all_predictions_before_reference_load',False),
    ('greedy_repeated_for_scoring',True),('training_executed',True),('encoder_executed',True),
    ('used_for_selection',True),('fresh_holdout',True),('saved_training_preprocessing_exact',False)])
def test_evaluation_recipe_refuses_scope_and_authority_drift(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed exposed'):subject.validate_plan(plan)


@pytest.mark.parametrize('count',[0,1,6,11,13])
def test_incomplete_global_barrier_never_reads_labels(count,monkeypatch):
    monkeypatch.setattr(subject,'bound_json',lambda *a:pytest.fail('reference material read before all predictions'))
    with pytest.raises(ValueError,match='all12 predictions'):
        subject.load_exposed_references({},[{}]*count)


def references_fixture(tmp_path):
    target={'rules':[]};vocabulary=['<pad>','<bos>','<eos>',json.dumps(target)]+['unused'+str(i) for i in range(28)]
    codec={'target_vocabulary':vocabulary};rows=[dict(id=str(i),source_text='New literal '+str(i)+'.',input=[1.,0.]) for i in range(48)]
    refs=[dict(id=r['id'],source_text=r['source_text'],source_sha256=hashlib.sha256(r['source_text'].encode()).hexdigest(),
        split='fresh_authored_holdout',codec_sha256=digest(codec),target_sha256=digest(target),target=target,target_ids=[1,3,2]) for r in rows]
    receipt=dict(schema='authored-scalar-holdout/v1',complete=True,references_sha256=digest(refs),
        source_rows_sha256=digest([{k:r[k] for k in ('id','source_text')} for r in rows]),sealed_comparison_sha256='original-plan',codec_sha256=digest(codec))
    receipt['receipt_sha256']=digest(receipt);inputs={}
    def save(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));inputs[str(path)]=subject.sha(path);return str(path)
    manifest=dict(references=save('references.json',refs),holdout_receipt=save('receipt.json',receipt),comparison_seal='original-plan',inputs=inputs)
    records=[]
    for d,s,a in subject.jobs():
        for role in subject.ROLES:
            name=f'{d}-{a}-{s}';path=save(name+'-'+role+'.json',dict(complete=True,predictions=[dict(id=r['id']) for r in rows],
                model_tensor_sha256='state-'+name+role,generation_reference_access=False,greedy_passes_per_row=1))
            records.append(dict(arm=name,role=role,predictions_ref=dict(path=path,sha256=inputs[path]),state_ref={'tensor_sha256':'state-'+name+role}))
    return dict(manifest=manifest,fresh_inputs={'dimensions':{'8':{'rows':rows}}},core=SimpleNamespace(digest=digest),donor={'codec':codec}),records,refs


def test_complete_saved_predictions_unlock_only_authenticated_old_references(tmp_path):
    ctx,records,refs=references_fixture(tmp_path);actual,receipt=subject.load_exposed_references(ctx,records)
    assert actual==refs and receipt['sealed_comparison_sha256']=='original-plan'


@pytest.mark.parametrize('mutation',[lambda records:records[0].update(role='initial'),
    lambda records:records[0]['state_ref'].update(tensor_sha256='wrong'),
    lambda records:records[0]['predictions_ref'].update(sha256='wrong')])
def test_unbound_role_state_or_prediction_blocks_reference_load(tmp_path,monkeypatch,mutation):
    ctx,records,refs=references_fixture(tmp_path);mutation(records)
    monkeypatch.setattr(subject,'bound_json',lambda *a:pytest.fail('labels read despite invalid prediction barrier'))
    with pytest.raises(ValueError):subject.load_exposed_references(ctx,records)


def test_target_codec_and_original_seal_are_not_reinterpreted(tmp_path):
    ctx,records,_=references_fixture(tmp_path);ctx['manifest']['comparison_seal']='new-training-plan'
    with pytest.raises(ValueError,match='original R6 reference'):subject.load_exposed_references(ctx,records)


def test_bound_json_checks_exact_parsed_bytes(tmp_path):
    path=tmp_path/'input.json';path.write_text('{"v":1}');manifest={'inputs':{str(path):subject.sha(path)}}
    assert subject.bound_json(manifest,path)=={'v':1}
    path.write_text('{"v":2}')
    with pytest.raises(ValueError,match='sealed artifact'):subject.bound_json(manifest,path)


def test_execution_saves_all_greedy_panels_then_scores_same_panels(tmp_path,monkeypatch):
    calls=[];plan=tmp_path/'plan.json';plan.write_text('{}')
    def save(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return dict(path=str(path),sha256=subject.sha(path))
    runs={f'{d}-{a}-{s}':dict(arm=f'{d}-{a}-{s}',states={role:{'tensor_sha256':str(d)+a+role} for role in subject.ROLES}) for d,s,a in subject.jobs()}
    original=dict(comparison_owner=SimpleNamespace(source_inventory=lambda *a:{}),comparison_parent_args='original')
    ctx=dict(original_context=original,helpers=SimpleNamespace(save=save),manifest={'inputs':{},'plan_sha256':subject.sha(plan)},plan={},
        saved_runs=runs,evaluation_extensions={},core=SimpleNamespace(digest=digest))
    def generate(ctx,lane,model,deadline):
        calls.append(('generate',model));return dict(elapsed_seconds=.01,model_tensor_sha256=model)
    def score(ctx,lane,model,prediction,refs,deadline):
        assert calls.count(('reference_load',None))==1 and len([r for r in calls if r[0]=='generate'])==12
        assert prediction['model_tensor_sha256']==model and prediction['previously_exposed'] and prediction['fresh_holdout'] is False
        calls.append(('score',model));return dict(elapsed_seconds=.01,fidelity={'metrics':{'ordered_exact':1,'syntax_valid':2}},teacher_forced={'token_cross_entropy':.5})
    owner=SimpleNamespace(prepare_lane=lambda c,d:{'dimension':d},restore_state=lambda c,l,r,role:(r['states'][role]['tensor_sha256'],{}),
        generate_panel=generate,score_panel=score)
    ctx['exposed_evaluator']=owner
    def load_refs(ctx,records):
        assert len(records)==12 and all(Path(r['predictions_ref']['path']).is_file() for r in records)
        assert len(calls)==12;calls.append(('reference_load',None));return ['refs'],{'receipt':'old'}
    monkeypatch.setattr(subject,'load_context',lambda args:ctx);monkeypatch.setattr(subject,'load_exposed_references',load_refs)
    result=subject.execute(SimpleNamespace(output=tmp_path/'output',plan=plan,extension_root=tmp_path))
    assert result['complete'] and len(result['panels'])==12 and result['training_executed'] is False
    assert [kind for kind,_ in calls]==['generate']*12+['reference_load']+['score']*12
    assert result['previously_exposed'] and result['fresh_holdout'] is False
