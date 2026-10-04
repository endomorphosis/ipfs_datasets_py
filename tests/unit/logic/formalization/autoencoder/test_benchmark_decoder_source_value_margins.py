"""Authentication and fixed-scope guards for actual-prefix diagnostics."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location('margin_driver_test',
    ROOT/'scripts/ops/autoencoder/benchmark_decoder_source_value_margins.py')
driver=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(driver)


@pytest.mark.parametrize('key,value',[
    ('training_executed',True),('optimizer_steps',False),('expected_panels',16),
    ('temperature',1),('fixed_decoder_output_limit',1024),('fixed_encoder_context_tokens',1024),
    ('strict_gates_changed',True),('reference_tokens_passed_to_generation',True),
    ('archived_greedy_predictions_must_match',False),('state_order',driver.STATES[:-1]),
    ('selected_controls',['conditioned','source_shuffle']),('batch_size',16),
])
def test_margin_recipe_rejects_changed_measurement(key,value):
    plan=deepcopy(driver.FIXED);driver.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed greedy margin recipe'):
        driver.validate_plan(plan)


def predecessor():
    root=Path('/evidence')
    manifest=dict(parent_public_manifest='public',parent_public_results='results',
        parent_summary=str(root/'summary.json'),state_catalog=driver.expected_catalog(root))
    names=driver.ARMS+['unchanged-1729','unchanged-2718']
    summary=dict(schema='decoder-source-value-training-comparison/v1',complete=True,
        runs=[dict(arm=name,training=dict(selected_epoch=0)) for name in names],**driver.FALSE)
    data={'public':dict(archive={'sha256':'archive'}),
        'results':dict(complete=True,archive={'sha256':'archive'}),str(root/'summary.json'):summary}
    helper=SimpleNamespace(read_bound=lambda path,*unused:deepcopy(data[path]))
    return manifest,data,helper


def test_exact_catalog_covers_eighteen_bound_replays():
    manifest,data,helper=predecessor()
    public,runs=driver.authenticate(manifest,helper)
    assert len(runs)==6
    catalog=manifest['state_catalog']
    assert [c['name'] for c in catalog]==driver.STATES
    assert sum(len(c['archived_evaluations']) for c in catalog)==18
    assert len(catalog[0]['archived_evaluations'])==2


@pytest.mark.parametrize('change',[
    'archive','role','state','evaluation','selected_epoch','missing_arm','authority'])
def test_predecessor_binding_rejects_role_state_control_and_authority_drift(change):
    manifest,data,helper=predecessor();summary=data['/evidence/summary.json']
    if change=='archive':data['results']['archive']['sha256']='other'
    elif change=='role':manifest['state_catalog'][0]['role']='last-attempt'
    elif change=='state':manifest['state_catalog'][0]['state_path']='/other-state.json'
    elif change=='evaluation':manifest['state_catalog'][1]['archived_evaluations']['train/conditioned']='/other-panel.json'
    elif change=='selected_epoch':summary['runs'][0]['training']['selected_epoch']=4
    elif change=='missing_arm':summary['runs'].pop()
    elif change=='authority':summary['admitted']=True
    with pytest.raises(ValueError):driver.authenticate(manifest,helper)
