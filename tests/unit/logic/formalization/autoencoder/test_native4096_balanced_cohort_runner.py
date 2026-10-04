"""Small runner controls: no pretrained model or native forward execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
RUNNER = ROOT / 'scripts/ops/autoencoder/benchmark_native4096_balanced_cohort.py'
spec = importlib.util.spec_from_file_location('native4096_balanced_cohort_runner_test_subject', RUNNER)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def donor_fixture(torch):
    shapes={'projection_down.weight':(8,384),'projection_down.bias':(8,),
        'projection_up.weight':(384,8),'projection_up.bias':(384,),
        'condition.weight':(32,384),'condition.bias':(32,),
        'target_embedding.weight':(32,16),'decoder.weight_ih_l0':(96,16),
        'decoder.weight_hh_l0':(96,32),'decoder.bias_ih_l0':(96,),'decoder.bias_hh_l0':(96,),
        'output.weight':(32,32),'output.bias':(32,)}
    state={}
    for name,shape in shapes.items():
        value=torch.arange(int(torch.tensor(shape).prod()),dtype=torch.float32).reshape(shape)/100000.
        state[name]=value.tolist()
    return {'schema':'shared-source-384-autoencoder/v2','dimension':384,
        'config':{'hidden_size':32,'token_embedding_dim':16,'projection_width':8},
        'codec':{'schema':'synthetic-original-codec','target_vocabulary':['<pad>','<bos>','<eos>']+[f't{i}' for i in range(29)]},
        'model_state':state}


def test_raw_donor_restores_every_tensor_and_preserves_rng():
    torch=pytest.importorskip('torch');checkpoint=donor_fixture(torch)
    before=copy.deepcopy(checkpoint);rng=torch.get_rng_state().clone()
    model=m.restore_raw_donor(checkpoint,torch)
    assert torch.equal(torch.get_rng_state(),rng) and checkpoint==before
    assert set(model.state_dict())==set(checkpoint['model_state'])
    for name,tensor in model.state_dict().items():
        assert tensor.dtype==torch.float32 and tensor.device.type=='cpu'
        assert torch.equal(tensor,torch.tensor(checkpoint['model_state'][name],dtype=torch.float32))


def test_raw_donor_does_not_inherit_float64_default():
    torch=pytest.importorskip('torch');checkpoint=donor_fixture(torch);previous=torch.get_default_dtype()
    try:
        torch.set_default_dtype(torch.float64)
        model=m.restore_raw_donor(checkpoint,torch)
    finally:torch.set_default_dtype(previous)
    assert all(tensor.dtype==torch.float32 for tensor in model.state_dict().values())


@pytest.mark.parametrize('change',['schema','dimension','hidden','token_width','projection_width','vocabulary',
    'missing_tensor','extra_tensor','shape','nan'])
def test_changed_donor_fails_before_constructing_pilot(change):
    torch=pytest.importorskip('torch');checkpoint=donor_fixture(torch)
    if change=='schema':checkpoint['schema']='production'
    elif change=='dimension':checkpoint['dimension']=4096
    elif change=='hidden':checkpoint['config']['hidden_size']=64
    elif change=='token_width':checkpoint['config']['token_embedding_dim']=8
    elif change=='projection_width':checkpoint['config']['projection_width']=4
    elif change=='vocabulary':checkpoint['codec']['target_vocabulary'].append('extra')
    elif change=='missing_tensor':del checkpoint['model_state']['condition.bias']
    elif change=='extra_tensor':checkpoint['model_state']['foreign.weight']=[0.]
    elif change=='shape':checkpoint['model_state']['condition.bias']=[0.]
    else:checkpoint['model_state']['condition.bias'][0]=float('nan')
    with pytest.raises(ValueError):m.restore_raw_donor(checkpoint,torch)


def test_real_project_import_closure_is_frozen_and_encoder_libraries_stay_lazy(tmp_path):
    frozen=tmp_path/'frozen'
    for relative in m.PRODUCERS:
        target=frozen/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
    code="""import importlib.util, importlib, json, pathlib, sys
runner=pathlib.Path(sys.argv[1]);root=pathlib.Path(sys.argv[2])
spec=importlib.util.spec_from_file_location('runner',runner);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
subject=m.install_frozen_namespace(root)
owner=importlib.import_module(m.PACKAGE+'.source_embeddings_4096_full_owner')
observed={}
for relative in m.PRODUCERS:
 name=relative[:-3].replace('/','.')
 module=sys.modules[name]
 assert pathlib.Path(module.__file__).resolve()==(root/relative).resolve()
 observed[name]=module.__file__
assert not {'torch','transformers','llama_cpp'} & set(sys.modules)
for count in range(1,len(m.PACKAGE.split('.'))+1):
 name='.'.join(m.PACKAGE.split('.')[:count])
 assert sys.modules[name].__path__==[str(root.joinpath(*name.split('.')))]
print(json.dumps(observed,sort_keys=True))
"""
    result=subprocess.run([sys.executable,'-I','-c',code,str(RUNNER),str(frozen)],
        text=True,capture_output=True,timeout=20,check=True,cwd=tmp_path)
    assert len(json.loads(result.stdout))==7


def test_preimported_project_refuses_instead_of_switching_trees(tmp_path):
    code="""import importlib.util,pathlib,sys,types
spec=importlib.util.spec_from_file_location('runner',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
foreign=types.ModuleType('ipfs_datasets_py');foreign.__path__=['/different/tree'];sys.modules['ipfs_datasets_py']=foreign
try:m.install_frozen_namespace(pathlib.Path(sys.argv[2]))
except ValueError:pass
else:raise AssertionError('mixed tree accepted')
assert sys.modules['ipfs_datasets_py'] is foreign
assert foreign.__path__==['/different/tree']
"""
    subprocess.run([sys.executable,'-I','-c',code,str(RUNNER),str(tmp_path)],check=True,timeout=10,cwd=tmp_path)


def test_missing_frozen_dependency_cannot_fall_back_to_editable_install(tmp_path):
    code="""import importlib.util,pathlib,sys
spec=importlib.util.spec_from_file_location('runner',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
try:m.install_frozen_namespace(pathlib.Path(sys.argv[2]))
except ModuleNotFoundError:pass
else:raise AssertionError('missing frozen source resolved elsewhere')
"""
    subprocess.run([sys.executable,'-I','-c',code,str(RUNNER),str(tmp_path)],check=True,timeout=10,cwd=tmp_path)



def test_balanced_plan_retains_guarded_native_and_decoding_limits():
    assert m.FIXED['schema']=='native4096-balanced-cohort-plan/v1'
    assert m.FIXED['optimizer_steps']==200 and m.FIXED['arm_count']==2
    assert m.FIXED['arms']==['joint_unscaled','joint_source_scaled']
    assert m.FIXED['unique_training_sources']==m.FIXED['development_sources']==12
    assert m.FIXED['native_forward_rows']==25
    assert m.FIXED['encoder_context_tokens']==m.FIXED['decoder_output_tokens']==512
    assert m.FIXED['native_deadline_seconds']==900 and m.FIXED['native_rss_limit_bytes']==8*1024**3
    assert m.FIXED['temperature']==0 and m.FIXED['validation_count']==12
    assert m.FIXED['development_status']=='previously_exposed_original_development_split'
    assert not m.FIXED['checkpoint_promoted'] and m.FIXED['bridge_names']==[]
    assert not m.FIXED['legal_ir_evaluate_provers'] and not m.FIXED['metric_disk_cache_used']
