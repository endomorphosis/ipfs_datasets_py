"""Frozen recipe, predecessor authentication and target-free diagnostic routing."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location('order_boundary_driver_test',ROOT/'scripts/ops/autoencoder/benchmark_decoder_order_boundaries.py')
driver=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(driver)


@pytest.mark.parametrize('key,value',[
    ('source_split_for_permutations','validation'),('representation_dimension',768),
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),
    ('temperature',1),('unique_order_rows',120),('permutation_pairs',72),
    ('duplicate_variant_aliases',0),('repeat_batch_sizes',[8]),
    ('total_encoder_row_observations',108),('boundary_splits',['train']),
    ('decoder_batch_size',1),('no_downloads',False),('selection_unchanged',False),
    ('generation_reference_count_access',True),('generation_reference_prefix_access',True),
    ('old_prediction_replay_required',False),('trained_weights_unchanged',False),
    ('native_qualification',True),('production_promotion_allowed',True),
    ('observation_thresholds_confer_success',True),
])
def test_plan_refuses_changed_source_scope_or_success(key,value):
    plan=deepcopy(driver.FIXED);driver.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed diagnostic recipe'):driver.validate_plan(plan)


def published_input(tmp_path,*,reference=False):
    p=tmp_path/'input.json';p.write_text('{"value":1}\n')
    digest=driver.sha(p);info=dict(sha256=digest,bytes=p.stat().st_size)
    manifest={'inputs':{str(p):digest}}
    public={'original_artifact_archive_paths':{},'members':{},'referenced_artifacts':{}}
    if reference:public['referenced_artifacts'][str(p)]=dict(info,kind='archive_member',dependency_id='prior',member='input.json')
    else:public['original_artifact_archive_paths'][str(p)]='input.json';public['members']['input.json']=info
    return p,manifest,public


@pytest.mark.parametrize('reference',[False,True])
def test_read_predecessor_checks_exact_member_bytes(tmp_path,reference):
    p,m,pub=published_input(tmp_path,reference=reference)
    assert driver.read_published(p,m,pub)=={'value':1}
    p.write_text('{"value":2}\n')
    with pytest.raises(ValueError,match='unbound'):driver.read_published(p,m,pub)
    m['inputs'][str(p)]=driver.sha(p)
    with pytest.raises(ValueError,match='published'):driver.read_published(p,m,pub)


def test_unknown_predecessor_reference_cannot_become_trusted_by_local_pin(tmp_path):
    p,m,pub=published_input(tmp_path,reference=True)
    pub['referenced_artifacts'][str(p)]['kind']='unverified_url'
    with pytest.raises(ValueError):driver.read_published(p,m,pub)


def test_exact_four_final_state_catalog_and_both_original_splits(tmp_path):
    rows=driver.expected_catalog(tmp_path/'summary.json')
    assert [r['arm'] for r in rows]==driver.ARMS
    assert len(rows)==4 and all(set(r['panels'])=={'train','validation'} for r in rows)
    assert all(r['state_path'].endswith('/last-attempt-state.json') for r in rows)


def test_helper_authentication_precedes_execution(tmp_path):
    p=tmp_path/'helper.py';marker=tmp_path/'started'
    p.write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
    with pytest.raises(ValueError):driver.load_helper(tmp_path,{},'helper.py','untrusted')
    assert not marker.exists()


def prediction():return dict(id='row',token_ids=[3,4],eos_reached=True,generation_status='eos')


def test_boundary_replay_compares_actual_four_fields_with_wider_saved_envelope():
    row=prediction();archived={'predictions':[dict(row,reconstructed_input=[0.]*384,exact_target=False)]}
    assert driver.validate_prediction_replay([row],archived,['row'])['complete']


@pytest.mark.parametrize('key,value',[('id','other'),('token_ids',[3,5]),('eos_reached',False),('generation_status','output_limit')])
def test_boundary_replay_refuses_generation_drift(key,value):
    row=prediction();archived={'predictions':[deepcopy(row)]};row[key]=value
    with pytest.raises(ValueError):driver.validate_prediction_replay([row],archived,['row'])


@pytest.mark.parametrize('extra',['target','target_ids','source_text','reference_count','components'])
def test_source_generation_rejects_reference_or_text_fields_before_model_call(extra):
    ctx={'core':SimpleNamespace()}
    row=dict(id='source',input=[0.]*384);row[extra]=[]
    with pytest.raises(ValueError,match='source-only'):driver.greedy_source_panel(ctx,None,[row])


def test_greedy_source_panel_preserves_parameters_rng_and_records_only_real_generation():
    import torch
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as exposure
    previous=torch.get_num_threads();torch.set_num_threads(1)
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__();self.offset=torch.nn.Parameter(torch.tensor(0.));self.dimension=384
        def project(self,x):return x+self.offset
        def start(self,x):return x
        def next_logits(self,tokens,state):
            values=torch.zeros(len(tokens),1,4);values[:,:,2]=1.
            return values,state
        def source_value_logits(self,x):return torch.zeros(len(x),8,4,4)
        def count_logits(self,x):return torch.zeros(len(x),32)
    try:
        model=Model();model.train();model.offset.grad=torch.tensor(2.)
        ctx={'core':core,'owners':{'long_span_count_exposure_training':exposure},
            'donor':{'input_transform':{'mean':[0.]*384,'scale':1.},'codec':{'target_vocabulary':['<pad>','<bos>','<eos>','{}']}}}
        rng=torch.random.get_rng_state().clone();digest=core.tensor_digest(model)
        rows=[dict(id=str(i),input=[float(i)]*384) for i in range(9)]
        result=driver.greedy_source_panel(ctx,model,rows)
        assert result['rows']==9 and [r['id'] for r in result['predictions']]==[r['id'] for r in rows]
        assert all(r['token_ids']==[] and r['eos_reached'] and r['generation_status']=='eos' for r in result['predictions'])
        assert result['projected_vectors']['8']==[8.]*384
        assert core.tensor_digest(model)==digest and torch.equal(rng,torch.random.get_rng_state())
        assert model.training and model.offset.grad.item()==2.
        assert result['training_executed'] is False and result['admitted'] is False
    finally:torch.set_num_threads(previous)
