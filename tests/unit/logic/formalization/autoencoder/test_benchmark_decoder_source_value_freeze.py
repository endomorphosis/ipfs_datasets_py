"""Frozen-body benchmark boundaries and published-control authentication."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location('freeze_benchmark_test',
    ROOT/'scripts/ops/autoencoder/benchmark_decoder_source_value_freeze.py')
driver = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(driver)
PARENT = importlib.util.spec_from_file_location('freeze_parent_test',
    ROOT/'scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py')
parent = importlib.util.module_from_spec(PARENT); PARENT.loader.exec_module(parent)


@pytest.mark.parametrize('key,value', [
    ('inherited_body_frozen',False),('only_source_value_head_trainable',False),
    ('inherited_decoder_and_count_trainable',True),('source_feature_normalization','center_rms'),
    ('source_value_guidance',False),('fixed_encoder_context_tokens',1024),
    ('fixed_decoder_output_limit',1024),('selection_unchanged',False),
    ('generation_reference_prefix_access',True),('generation_reference_count_access',True),
    ('expected_optimizer_steps_per_arm',341),('seed_order',[1729]),
    ('expected_source_value_presentations_per_candidate',True),('postfit_controls',[]),
    ('temperature',1),('native_qualification',True),
])
def test_fixed_recipe_cannot_change_gates_geometry_exposure_or_training_scope(key,value):
    plan=deepcopy(driver.FIXED);driver.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='unsupported fixed source-value freeze'):
        driver.validate_plan(plan)


def report():
    return dict(initial_weights_sha256='initial',optimizer_steps=340,row_presentations=2440,
        valid_target_token_presentations=225840,training_rows_sha256='train',validation_rows_sha256='validation',
        training_references_sha256='train-refs',validation_references_sha256='validation-refs',
        codec_sha256='codec',curriculum=[dict(name='stage',epochs=80)],
        committed_decoder_batch_ids_sha256='decoder-ids',committed_count_batch_ids_sha256='count-ids',
        count_training_row_presentations=2440,count_training_presentations_by_class={'1':610,'2':610,'4':610,'8':610},
        count_mean_loss_exposure_by_class={'1':85.,'2':85.,'4':85.,'8':85.},
        source_value_presentations=25600,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',strategy='semantic_fields',config={'seed':1729,'learning_rate':.001},
        selection='per_length_nonregression_then_fidelity_progress_then_reference_ce',
        optimizer_instance_count=1,optimizer_reinitialized_between_stages=False,stopped_reason='epochs_completed',
        baseline={'numerical':{'ce':4.2},'fidelity':{'ordered_exact':0},'source_values':{'correct':0}})


def test_comparison_matches_controls_not_expected_training_outcomes():
    prior=report();actual=deepcopy(prior)
    actual.update(selected_epoch=4,gradient_norms={'max':3.},elapsed_seconds=3.,selected_weights_sha256='new',
        history=[{'learning_rate':.00025}],frozen_parameter_names=['body.everything'])
    compared=driver.compare_joint_exposure(actual,prior)
    assert compared['complete'] and not compared['same_actual_gradient_or_learning_rate_path_claimed']
    assert not compared['joint_control_retrained']


@pytest.mark.parametrize('key,value', [
    ('initial_weights_sha256','different'),('committed_decoder_batch_ids_sha256','different'),
    ('committed_count_batch_ids_sha256','different'),('source_value_weight',0.),('source_value_presentations',0),
    ('baseline',{'numerical':{'ce':.1}}),('selection','ce_only_diagnostic'),
    ('config',{'seed':1729,'learning_rate':.01}),('optimizer_steps',339),('stopped_reason','deadline'),
])
def test_input_exposure_baseline_or_gate_drift_refuses(key,value):
    prior=report();actual=deepcopy(prior);actual[key]=value
    with pytest.raises(ValueError,match='joint control input/exposure/baseline/gate differs'):
        driver.compare_joint_exposure(actual,prior)


def fixture(tmp_path):
    manifest={'inputs':{}}
    published={'archive':{'sha256':'archive','bytes':1},'members':{},'original_artifact_archive_paths':{}}
    def save(path,value,index=True):
        path.parent.mkdir(parents=True,exist_ok=True)
        raw=json.dumps(value,sort_keys=True).encode();path.write_bytes(raw)
        digest=hashlib.sha256(raw).hexdigest();manifest['inputs'][str(path)]=digest
        if index:
            member=path.relative_to(tmp_path).as_posix()
            published['members'][member]={'sha256':digest,'bytes':len(raw)}
            published['original_artifact_archive_paths'][str(path)]=member
        return str(path)
    root=tmp_path/'results';runs=[]
    for seed in (1729,2718):
        runs.append(dict(arm='unchanged-'+str(seed)))
        for recipe in driver.ARMS:
            name=recipe['name']+'-'+str(seed)
            training=dict(stopped_reason='epochs_completed',selected_epoch=0,
                selected_weights_sha256='selected',last_complete_attempt_weights_sha256='last')
            run=dict(arm=name,recipe=recipe,seed=seed,training=training,budget_completed=True);runs.append(run)
            save(root/name/'training.json',training)
            for role in ('selected','last-attempt'):
                state=dict(schema='private-source-value-state/v1',role=role,recipe=recipe,
                    tensor_sha256='selected' if role=='selected' else 'last',model_state={'tensor':[0.]},**driver.FALSE)
                save(root/name/(role+'-state.json'),state)
                for label,split,control in driver.CONTROLS:
                    panel=dict(report=dict(complete=True,generation_target_access=False,generation_temperature=0),
                        execution={'kind':control},predictions=[{}]*48)
                    save(root/name/role/('evaluation-'+label+'.json'),panel)
    summary=dict(schema='decoder-source-value-training-comparison/v1',complete=True,runs=runs,**driver.FALSE)
    manifest['prior_source_value_summary']=save(root/'summary.json',summary)
    manifest['prior_source_value_public_manifest']=save(tmp_path/'manifest.json',published,index=False)
    manifest['prior_source_value_public_results']=save(tmp_path/'public-results.json',{'archive':published['archive']},index=False)
    return manifest,save,published,summary


def test_authenticate_complete_published_joint_inventory_without_retraining(tmp_path):
    manifest,_,_,_=fixture(tmp_path)
    published,runs=driver.authenticate_joint_controls(manifest,parent.read_bound)
    assert len(runs)==4
    for value in runs.values():
        assert len(value['panels']['selected'])==len(value['panels']['last-attempt'])==5
        assert 'model_state' in value['states']['selected']
        assert 'model_state' not in value['states']['last-attempt']


@pytest.mark.parametrize('change', ['bytes','unpin','archive','recipe','selected_epoch','target_access','state_role'])
def test_authentication_refuses_joint_provenance_and_control_drift(tmp_path,change):
    manifest,save,published,summary=fixture(tmp_path)
    root=Path(manifest['prior_source_value_summary']).parent
    report_path=root/'conditioning48-1729'/'training.json'
    if change=='bytes':report_path.write_text('{}')
    elif change=='unpin':del manifest['inputs'][str(report_path)]
    elif change=='archive':
        published['members'][published['original_artifact_archive_paths'][str(report_path)]]['sha256']='wrong'
    elif change in ('recipe','selected_epoch'):
        run=next(run for run in summary['runs'] if run['arm']=='conditioning48-1729')
        if change=='recipe':run['recipe']={**run['recipe'],'source_value_weight':0.}
        else:
            run['training']['selected_epoch']=4
            save(report_path,run['training'])
        save(Path(manifest['prior_source_value_summary']),summary)
    elif change=='target_access':
        path=root/'conditioning48-1729'/'selected'/'evaluation-training.json';value=json.loads(path.read_text())
        value['report']['generation_target_access']=True;save(path,value)
    else:
        path=root/'conditioning48-1729'/'last-attempt-state.json';value=json.loads(path.read_text())
        value['role']='selected';save(path,value)
    if change not in ('bytes','unpin'):
        save(Path(manifest['prior_source_value_public_manifest']),published,index=False)
    with pytest.raises(ValueError):driver.authenticate_joint_controls(manifest,parent.read_bound)


def test_helper_hash_is_checked_before_import_execution(tmp_path):
    source=tmp_path/'helper.py';marker=tmp_path/'ran'
    source.write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
    with pytest.raises(ValueError,match='frozen benchmark helper differs'):
        driver.load_helper(tmp_path,{'helper.py':'wrong'},'helper.py','bad_helper')
    assert not marker.exists()


def diagnostic_fixture(tmp_path):
    manifest={'inputs':{}}
    def save(name,value):
        path=tmp_path/name;raw=json.dumps(value,sort_keys=True).encode();path.write_bytes(raw)
        digest=hashlib.sha256(raw).hexdigest();manifest['inputs'][str(path)]=digest
        return str(path),digest,len(raw)
    summary=dict(schema='decoder-source-value-margins-comparison/v1',complete=True,panels=[{}]*18,
        training_executed=False,optimizer_steps=0,archived_predictions_matched=True,**driver.FALSE)
    path,digest,size=save('summary.json',summary)
    manifest['diagnostic_summary']=path
    audit=dict(schema='independent-source-value-margins-audit/v1',phase='diagnostic',complete=True,
        all_pins_match=True,resource_status='released',findings=[],failed_check_count=0,
        artifacts={path:{'sha256':digest,'bytes':size}})
    audit_path,audit_digest,_=save('audit.json',audit)
    manifest['diagnostic_audit']=audit_path
    manifest['diagnostic_decision']=dict(summary_sha256=digest,audit_sha256=audit_digest,
        rationale='Test fixed inherited weights after reviewing source margins.')
    return manifest,summary,audit,save


def test_completed_margin_decision_is_required_before_training_imports(tmp_path):
    manifest,_,_,_=diagnostic_fixture(tmp_path)
    decision=driver.authenticate_diagnostic_decision(manifest,parent.read_bound)
    assert decision['complete'] and decision['summary_sha256']==manifest['diagnostic_decision']['summary_sha256']


@pytest.mark.parametrize('change',['missing','empty_rationale','decision_sha','summary_bytes','summary_incomplete',
    'summary_authority','summary_panels','audit_findings','audit_phase','audit_summary_sha','audit_unreleased'])
def test_training_precondition_refuses_incomplete_unbound_or_qualifying_diagnostics(tmp_path,change):
    manifest,summary,audit,save=diagnostic_fixture(tmp_path)
    if change=='missing':del manifest['diagnostic_decision']
    elif change=='empty_rationale':manifest['diagnostic_decision']['rationale']='  '
    elif change=='decision_sha':manifest['diagnostic_decision']['summary_sha256']='wrong'
    elif change=='summary_bytes':Path(manifest['diagnostic_summary']).write_text('{}')
    else:
        if change=='summary_incomplete':summary['complete']=False
        elif change=='summary_authority':summary['qualified']=True
        elif change=='summary_panels':summary['panels']=summary['panels'][:-1]
        elif change=='audit_findings':audit['findings']=[{'finding':'problem'}]
        elif change=='audit_phase':audit['phase']='head-only'
        elif change=='audit_summary_sha':audit['artifacts'][manifest['diagnostic_summary']]['sha256']='wrong'
        elif change=='audit_unreleased':audit['resource_status']='active'
        if change.startswith('summary_'):
            path,digest,size=save('summary.json',summary);manifest['diagnostic_decision']['summary_sha256']=digest
            audit['artifacts'][path]={'sha256':digest,'bytes':size}
        _,digest,_=save('audit.json',audit);manifest['diagnostic_decision']['audit_sha256']=digest
    with pytest.raises(ValueError):driver.authenticate_diagnostic_decision(manifest,parent.read_bound)
