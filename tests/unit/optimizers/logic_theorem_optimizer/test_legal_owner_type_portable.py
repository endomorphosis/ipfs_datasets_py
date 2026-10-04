"""Relocation, source-only parity and fail-closed data-only loader checks."""
from copy import deepcopy
import hashlib
import json
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
from pathlib import Path
import shutil
import importlib.util
import pytest
import torch
from safetensors.torch import save
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_owner_type_portable as p
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_ownership_head as old


def q(source, occurrence=0):
    needle='within 10 days'; starts=[i for i in range(len(source)) if source.startswith(needle,i)]; a=starts[occurrence]
    return {'id':'opaque-'+str(occurrence),'source_text':source,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'proposed_time_span':{'char_start':a,'char_end':a+len(needle)}}


def save_manifest(folder, manifest):
    raw=p.canonical(manifest)+b'\n'; (folder/'manifest.json').write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    torch.set_num_threads(1)
    config={'seed':1730,'embedding_dim':16,'hidden_size':32,'trigger_enabled':True,'latent_dimension':0}
    source=old.mixed._model(torch,config)
    parent={'model_config':config,'model_state':{k:v.tolist() for k,v in source.state_dict().items()}}
    reference=old._model(torch,parent,{'seed':1730,'arm':'finetune_occurrence'}).eval()
    needed=p._model(torch).state_dict(); state={k:reference.state_dict()[k].detach().contiguous() for k in needed}
    folder=tmp_path/'export';folder.mkdir()
    payload=save(state);(folder/'weights.safetensors').write_bytes(payload)
    manifest={'schema':p.SCHEMA,'config':deepcopy(p.CONFIG),'authority':deepcopy(p.FALSE),
              'loader_sha256':hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest(),
              'environment':{'torch_version':str(torch.__version__),'inference_threads':1,'device':'cpu'},
              'source_checkpoint':{'sha256':'1'*64,'bytes':42,'schema':'legal-paired-temporal-owner-type-checkpoint/v1'},
              'weights':{'filename':'weights.safetensors','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),
                         'tensors':{k:{'shape':list(v.shape),'dtype':'float32'} for k,v in state.items()}}}
    pin=save_manifest(folder,manifest)
    owner=old.TemporalOwnershipHead.__new__(old.TemporalOwnershipHead)
    owner.torch=torch;owner.model=reference;owner.encoder_batch_forwards=owner.encoder_source_evaluations=0
    return folder,manifest,pin,owner,state


def test_complete_output_parity_with_inherited_graph_and_unequal_lengths(bundle):
    folder,_,pin,owner,_=bundle
    rows=[q('Straße Registry shall file within 10 days.'),q('Board shall file within 10 days unless notice arrived within 10 days.',1)]
    portable=p.PortableOwnerType(folder,expected_manifest_sha256=pin)
    assert portable.predict_many(rows)==owner.predict_many(rows)
    assert all(not x.requires_grad for x in portable.model.parameters())
    assert portable.encoder_batch_forwards==1 and portable.encoder_source_evaluations==2


def test_relocation_loads_explicit_local_module_without_repository_imports(bundle,tmp_path):
    folder,_,pin,owner,_=bundle
    moved=tmp_path/'elsewhere';shutil.copytree(folder,moved)
    shutil.copyfile(p.__file__,tmp_path/'manual_loader.py')
    spec=importlib.util.spec_from_file_location('portable_relocated_test',tmp_path/'manual_loader.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    queries=[q('Registry shall file within 10 days.')]
    assert module.PortableOwnerType(moved,expected_manifest_sha256=pin).predict_many(queries)==owner.predict_many(queries)


def test_id_not_feature_and_two_occurrences_are_distinct_inputs(bundle):
    folder,_,pin,_,_=bundle;model=p.PortableOwnerType(folder,expected_manifest_sha256=pin)
    source='Within words Registry shall file within 10 days unless notice arrived within 10 days.'
    rows=[q(source,0),q(source,1)];changed=deepcopy(rows);changed[0]['id']='renamed'
    before=model.predict_many(rows);after=model.predict_many(changed)
    assert before[0]['logits']==after[0]['logits']
    assert before[0]['time_token_span']!=before[1]['time_token_span']
    assert before[0]['logits']!=before[1]['logits']


@pytest.mark.parametrize('mutation',['config_alias','threshold','extra_config','authority','loader','environment','path','extra_manifest'])
def test_manifest_mutations_fail_even_with_repaired_outer_hash(bundle,mutation):
    folder,m,_,_,_=bundle
    if mutation=='config_alias':m['config']['hidden_size']=32.0
    if mutation=='threshold':m['config']['threshold']=.7
    if mutation=='extra_config':m['config']['remote_code']='evil.py'
    if mutation=='authority':m['authority']['pipeline_promotion']=True
    if mutation=='loader':m['loader_sha256']='0'*64
    if mutation=='environment':m['environment']['inference_threads']=True
    if mutation=='path':m['weights']['filename']='../weights.safetensors'
    if mutation=='extra_manifest':m['pickle']='evil.pkl'
    with pytest.raises(ValueError):p.PortableOwnerType(folder,expected_manifest_sha256=save_manifest(folder,m))


@pytest.mark.parametrize('mutation',['nan','dtype','shape','missing','extra','padding'])
def test_tensor_mutations_fail_with_repaired_weight_and_manifest_hashes(bundle,mutation):
    folder,m,_,_,state=bundle;state={k:v.clone() for k,v in state.items()}
    key='head.0.weight'
    if mutation=='nan':state[key][0,0]=float('nan')
    if mutation=='dtype':state[key]=state[key].double()
    if mutation=='shape':state[key]=state[key][:-1]
    if mutation=='missing':state.pop(key)
    if mutation=='extra':state['untrusted.weight']=torch.zeros(1)
    if mutation=='padding':state['source.byte_embedding.weight'][0,0]=1
    payload=save(state);(folder/'weights.safetensors').write_bytes(payload)
    m['weights']['bytes']=len(payload);m['weights']['sha256']=hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError):p.PortableOwnerType(folder,expected_manifest_sha256=save_manifest(folder,m))


@pytest.mark.parametrize('mutation',['label','owner','badsha','unaligned','booloffset','reversed','pastend','empty','too_long'])
def test_invalid_or_label_bearing_source_queries_rejected(bundle,mutation):
    folder,_,pin,_,_=bundle;row=q('Registry shall file within 10 days.')
    if mutation=='label':row['label']='norm'
    if mutation=='owner':row['owner_span']=[0,8]
    if mutation=='badsha':row['source_sha256']='0'*64
    if mutation=='unaligned':row['proposed_time_span']['char_start']+=1
    if mutation=='booloffset':row['proposed_time_span']['char_start']=True
    if mutation=='reversed':row['proposed_time_span']['char_end']=0
    if mutation=='pastend':row['proposed_time_span']['char_end']=10000
    if mutation=='empty':row['source_text']=''
    if mutation=='too_long':row=q('x '*257+'within 10 days')
    with pytest.raises(ValueError):p.PortableOwnerType(folder,expected_manifest_sha256=pin).predict_many([row])


def test_weights_hash_and_external_manifest_pin_are_mandatory(bundle):
    folder,m,pin,_,_=bundle
    with pytest.raises(ValueError):p.PortableOwnerType(folder,expected_manifest_sha256='0'*64)
    payload=(folder/'weights.safetensors').read_bytes();(folder/'weights.safetensors').write_bytes(payload[:-1]+bytes([payload[-1]^1]))
    with pytest.raises(ValueError):p.PortableOwnerType(folder,expected_manifest_sha256=pin)


def test_tokenizer_matches_frozen_unicode_casefold_and_offsets():
    source='Straße §7 May 3, 2030: Registry’s board shall file within 10 days.'
    assert p.tokenize_source(source)==old.span.tokenize_source(source)


def test_duplicate_json_key_and_nonfinite_json_rejected():
    for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
        with pytest.raises(ValueError):p._read_json(raw)
