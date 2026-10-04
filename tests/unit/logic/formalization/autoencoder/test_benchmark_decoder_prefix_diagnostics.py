"""The diagnostic must fail closed on altered source, state, or archive roles."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location('prefix_benchmark_test',
    ROOT/'scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py')
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


@pytest.mark.parametrize('key,value', [('training_executed',True),('new_generation_allowed',True),
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('temperature',1),
    ('raw_logits_retained',False),('state_order',driver.STATES[:-1]),('optimizer_steps',False)])
def test_plan_rejects_changed_execution_or_geometry(key,value):
    plan=copy.deepcopy(driver.FIXED)
    driver.validate_plan(plan)
    plan[key]=value
    with pytest.raises(ValueError,match='fixed diagnostic recipe'):
        driver.validate_plan(plan)


def write_input(tmp_path, manifest, published, name, value):
    path=tmp_path/name
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,sort_keys=True).encode()
    path.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    manifest['inputs'][str(path)]=digest
    published['original_artifact_archive_paths'][str(path)]=name
    published['members'][name]=dict(sha256=digest,bytes=len(raw))
    return str(path)


def test_read_requires_both_pin_and_published_member(tmp_path):
    manifest={'inputs':{}}
    published={'original_artifact_archive_paths':{},'members':{}}
    path=write_input(tmp_path,manifest,published,'a.json',{'x':1})
    assert driver.read_bound(path,manifest,published)=={'x':1}
    published['members']['a.json']['bytes']+=1
    with pytest.raises(ValueError,match='published predecessor'):
        driver.read_bound(path,manifest,published)
    Path(path).write_text('{"x":2}')
    with pytest.raises(ValueError,match='changed input'):
        driver.read_bound(path,manifest)


def predecessor(tmp_path):
    manifest={'inputs':{}}
    published={'archive':{'sha256':'a'*64},'original_artifact_archive_paths':{},'members':{}}
    runs=[]
    selected=[]
    for arm in driver.ARMS:
        selected.append(write_input(tmp_path,manifest,published,arm+'/selected-state.json',dict(
            role='selected',selected=True,model_state={'x':[1.]},tensor_sha256='b'*64,weights_sha256='c'*64)))
        runs.append(dict(arm=arm,training=dict(selected_epoch=0,selected_weights_sha256='b'*64)))
    manifest['parent_summary']=write_input(tmp_path,manifest,published,'summary.json',dict(complete=True,runs=runs,**driver.FALSE))
    manifest['selected_state_equivalence_paths']=selected
    manifest['state_catalog']=[]
    for name,arm,role in [('selected-common',driver.ARMS[0],'selected')]+[(a+'-last',a,'last-attempt') for a in driver.ARMS]:
        manifest['state_catalog'].append(dict(name=name,prior_arm=arm,role=role,
            state_path=str(tmp_path/arm/(role+'-state.json')),
            archived_evaluations={key:str(tmp_path/arm/role/('evaluation-'+label+'.json')) for key,label in driver.LABELS.items()}))
    # Published index/result are independently pinned; not members of themselves.
    manifest['parent_public_results']=write_input(tmp_path,manifest,published,'public-results.json',{'archive':published['archive']})
    path=tmp_path/'public-manifest.json';raw=json.dumps(published,sort_keys=True).encode();path.write_bytes(raw)
    manifest['inputs'][str(path)]=hashlib.sha256(raw).hexdigest()
    manifest['parent_public_manifest']=str(path)
    return manifest


def test_common_selected_state_deduplicated_only_after_authentication(tmp_path):
    manifest=predecessor(tmp_path)
    _,runs,dedup=driver.authenticate_predecessor(manifest)
    assert len(runs)==4 and dedup['source_state_count']==4 and dedup['executed_state_count']==1


@pytest.mark.parametrize('change', ['role','duplicate','selected_inventory','missing_pin','selected_bytes'])
def test_predecessor_rejects_role_and_provenance_changes(tmp_path,change):
    manifest=predecessor(tmp_path)
    if change=='role':manifest['state_catalog'][1]['role']='selected'
    elif change=='duplicate':manifest['state_catalog'][1]=manifest['state_catalog'][0]
    elif change=='selected_inventory':manifest['selected_state_equivalence_paths'].pop()
    elif change=='missing_pin':manifest['inputs'].pop(manifest['selected_state_equivalence_paths'][0])
    else:Path(manifest['selected_state_equivalence_paths'][1]).write_text('{}')
    with pytest.raises(ValueError):driver.authenticate_predecessor(manifest)


class Core:
    @staticmethod
    def digest(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def test_unavailable_is_only_train_zero_and_never_fabricates_predictions():
    catalog={'archived_evaluations':{}}
    result=driver.archive_for_panel(catalog,'train',{'kind':'zero_condition'},[],{},None,Core,{}, {})
    assert result[0] is None and result[2] is None and result[1]['status']=='unavailable'
    with pytest.raises(ValueError,match='unexpected absent'):
        driver.archive_for_panel(catalog,'validation',{'kind':'conditioned'},[],{},None,Core,{}, {})


def test_export_must_remain_rejected_and_bound_to_parent():
    catalog={'role':'last-attempt'}
    value=dict(schema='private-transition-ramp-state/v1',role='last-attempt',selected=False,
        optimizer_resumable=False,codec={},model_state={'x':[1.]},tensor_sha256='b'*64,**driver.FALSE)
    value['weights_sha256']=Core.digest(value['model_state'])
    run={'training':{'last_complete_attempt_weights_sha256':'b'*64}}
    driver.validate_export(value,catalog,run,Core,{})
    value['qualified']=True
    with pytest.raises(ValueError,match='authority'):
        driver.validate_export(value,catalog,run,Core,{})
    value['qualified']=False;value['tensor_sha256']='d'*64
    with pytest.raises(ValueError,match='parent role'):
        driver.validate_export(value,catalog,run,Core,{})
