"""Synthetic postfit lifecycle controls; no model or encoder execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

P=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('_test_mixture_styles',P/'scripts/ops/autoencoder/evaluate_training_mixture_styles.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@pytest.mark.parametrize('key,value',[('dimensions',[384]),('roles',['selected']),('panel_count',4),
    ('samples_per_panel',47),('temperature',1),('context_tokens',1024),('output_tokens',1024),
    ('vocabulary_size',31),('used_for_selection',True),('fresh_holdout',True),
    ('all_predictions_before_reference_load',False),('training_executed',True),('encoder_executed',True)])
def test_recipe_preserves_full_endpoint_and_authority_boundaries(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='recipe differs'):subject.validate_plan(plan)


def fixture(tmp_path):
    rows=[dict(id=f'synthetic:{i}',source_text=f'Synthetic source {i}.',input=[float(i)]) for i in range(48)]
    lanes={d:dict(fresh_rows=deepcopy(rows),fresh_contexts={'synthetic':'context'}) for d in (384,768)}
    runs={};records=[];manifest={'inputs':{}}
    for d in (384,768):
        for a in subject.ARMS:
            states={r:dict(tensor_sha256=digest([d,a,r]),path=f'synthetic-state-{d}-{a}-{r}') for r in subject.ROLES}
            runs[d,a]=dict(states=states)
            for r in subject.ROLES:
                panel=dict(complete=True,model_tensor_sha256=states[r]['tensor_sha256'],
                    source_rows_sha256=digest(rows),source_contexts_sha256=digest(lanes[d]['fresh_contexts']),
                    predictions=[dict(id=x['id'],token_ids=[1,2]) for x in rows],generation_reference_access=False,
                    greedy_passes_per_row=1,generation_temperature=0,max_target_tokens=512)
                p=tmp_path/f'{d}-{a}-{r}.json';p.write_text(json.dumps(panel))
                records.append(dict(dimension=d,arm=a,role=r,state_ref=states[r],
                    predictions_ref=dict(path=str(p),sha256=subject.sha(p))))
    codec={'target_vocabulary':['PAD','BOS','EOS','{','}']+[str(i) for i in range(27)]}
    refs=[dict(id=r['id'],source_text=r['source_text'],source_sha256=hashlib.sha256(r['source_text'].encode()).hexdigest(),
        target={},target_sha256=digest({}),codec_sha256=digest(codec),target_ids=[1,3,4,2]) for r in rows]
    receipt=dict(complete=True,schema='authored-modality-holdout/v3',references_sha256=digest(refs),
        source_rows_sha256=digest([{k:r[k] for k in ('id','source_text')} for r in rows]),codec_sha256=digest(codec),
        sealed_comparison_sha256=subject.FIXED['comparison_seal'])
    receipt['receipt_sha256']=digest(receipt)
    for name,value in [('references',refs),('holdout_receipt',receipt)]:
        p=tmp_path/(name+'.json');p.write_text(json.dumps(value));manifest[name]=str(p);manifest['inputs'][str(p)]=subject.sha(p)
    return manifest,records,runs,lanes,codec,refs


def test_all_eight_complete_panels_allow_reference_load(tmp_path):
    manifest,records,runs,lanes,codec,refs=fixture(tmp_path)
    assert subject.load_references(manifest,records,runs,lanes,codec,digest)[0]==refs


@pytest.mark.parametrize('mutation',['missing','duplicate','file','state','source','contexts','ids','labels','temperature','repeat','partial'])
def test_any_invalid_prediction_refuses_before_reference_parse(tmp_path,monkeypatch,mutation):
    manifest,records,runs,lanes,codec,_=fixture(tmp_path)
    if mutation=='missing':records.pop()
    elif mutation=='duplicate':records[-1]=deepcopy(records[0])
    elif mutation=='state':records[0]['state_ref']=dict(records[0]['state_ref'],tensor_sha256='wrong')
    else:
        record=records[0];p=Path(record['predictions_ref']['path']);value=json.loads(p.read_bytes())
        if mutation=='file':p.write_text('{}')
        else:
            if mutation=='source':value['source_rows_sha256']='changed'
            elif mutation=='contexts':value['source_contexts_sha256']='changed'
            elif mutation=='ids':value['predictions'].pop()
            elif mutation=='labels':value['generation_reference_access']=True
            elif mutation=='temperature':value['generation_temperature']=.5
            elif mutation=='repeat':value['greedy_passes_per_row']=2
            elif mutation=='partial':value['complete']=False
            p.write_text(json.dumps(value));record['predictions_ref']['sha256']=subject.sha(p)
    monkeypatch.setattr(subject,'bound',lambda *a:pytest.fail('reference opened before complete durable prediction gate'))
    with pytest.raises(ValueError):subject.load_references(manifest,records,runs,lanes,codec,digest)


def test_source_order_and_reference_provenance_are_separate_checks(tmp_path):
    manifest,records,runs,lanes,codec,_=fixture(tmp_path)
    p=Path(manifest['references']);refs=json.loads(p.read_bytes());refs[0]['source_text']='changed';p.write_text(json.dumps(refs))
    manifest['inputs'][str(p)]=subject.sha(p)
    with pytest.raises(ValueError,match='reference receipt'):subject.load_references(manifest,records,runs,lanes,codec,digest)


@pytest.mark.parametrize('times,calls',[([2.],0),([0.,2.],1)])
def test_restore_obeys_shared_deadline_before_and_after_copy(monkeypatch,times,calls):
    from types import SimpleNamespace
    values=iter(times);observed=[]
    monkeypatch.setattr(subject.time,'monotonic',lambda:next(values))
    owner=SimpleNamespace(restore_endpoint=lambda *a:observed.append('restore'))
    with pytest.raises(TimeoutError):subject.restore_before_deadline(owner,{}, {},'selected',1.)
    assert len(observed)==calls
