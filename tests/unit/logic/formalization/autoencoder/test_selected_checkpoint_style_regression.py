"""The exposed regression barrier is independent of training and selection."""
from copy import deepcopy
import importlib.util,json
from pathlib import Path
import pytest
P=Path(__file__).resolve().parents[5];PATH=P/'scripts/ops/autoencoder/evaluate_selected_checkpoint_style_regression.py'
s=importlib.util.spec_from_file_location('_selected_style_tests',PATH);subject=importlib.util.module_from_spec(s);s.loader.exec_module(subject)


def records(tmp_path):
 ids=[f'source{i}' for i in range(48)];out=[]
 for d in (384,768):
  for role in subject.ROLES:
   p=tmp_path/f'{d}-{role}.json';p.write_text(json.dumps(dict(complete=True,generation_reference_access=False,model_tensor_sha256=f'{d}-{role}',predictions=[dict(id=x) for x in ids],generation_temperature=0,max_target_tokens=512,greedy_passes_per_row=1)))
   out.append(dict(dimension=d,role=role,state_ref={'tensor_sha256':f'{d}-{role}'},predictions_ref={'path':str(p),'sha256':subject.sha(p)}))
 return out,{384:ids,768:ids}


def test_all_four_state_bound_predictions_required(tmp_path):
 rows,ids=records(tmp_path);subject.validate_barrier(rows,ids)
 for subset in (rows[:2],rows[1:],rows[::-1],[rows[0]]*4):
  with pytest.raises(ValueError):subject.validate_barrier(subset,ids)


@pytest.mark.parametrize('field,value',[('complete',False),('generation_reference_access',True),('model_tensor_sha256','different'),('generation_temperature',1),('max_target_tokens',1024),('greedy_passes_per_row',2),('predictions',[])])
def test_rehashed_invalid_predictions_still_rejected(tmp_path,field,value):
 rows,ids=records(tmp_path);p=Path(rows[0]['predictions_ref']['path']);data=json.loads(p.read_bytes());data[field]=value;p.write_text(json.dumps(data));rows[0]['predictions_ref']['sha256']=subject.sha(p)
 with pytest.raises(ValueError):subject.validate_barrier(rows,ids)


def test_unsealed_prediction_modification_is_rejected(tmp_path):
 rows,ids=records(tmp_path);Path(rows[-1]['predictions_ref']['path']).write_text('{}')
 with pytest.raises(ValueError):subject.validate_barrier(rows,ids)


@pytest.mark.parametrize('key,value',[('panel_count',2),('style_cohort_already_exposed',False),('used_for_selection',True),('training_executed',True),('fresh_holdout',True),('context_tokens',1024),('roles',['selected']),('source_vectors_reused',False)])
def test_registered_exposure_and_scope_cannot_change(key,value):
 plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
 with pytest.raises(ValueError):subject.validate_plan(plan)
