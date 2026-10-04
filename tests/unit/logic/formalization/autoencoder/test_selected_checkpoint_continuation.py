"""Closed follow-up driver contract; no teacher, encoder or corpus model work."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

P=Path(__file__).resolve().parents[5]
PATH=P/'scripts/ops/autoencoder/benchmark_selected_checkpoint_continuation.py'
SPEC=importlib.util.spec_from_file_location('_selected_continuation_tests',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def test_only_selected_384_and_768_from_r10_high_rate_are_registered():
 assert subject.ENDPOINTS=={'384':{'arm':'384-continue-lr001-1729','role':'selected'},'768':{'arm':'768-continue-lr001-1729','role':'selected'}}
 assert subject.FIXED['dimensions']==[384,768] and subject.FIXED['fit_count']==2
 assert subject.ARM==dict(name='continue-lr0001',learning_rate=.0001)
 assert subject.FIXED['optimizer_steps_per_fit']==170 and subject.FIXED['row_presentations']==1220
 assert subject.FIXED['valid_target_token_presentations']==112920 and subject.FIXED['source_value_presentations']==12800
 assert subject.FIXED['inherited_plateau_scheduler_unchanged']
 assert not subject.FIXED['new_cohort_read'] and not subject.FIXED['new_cohort_used_for_selection']


@pytest.mark.parametrize('key,value', [('dimensions',[8,384,768]),('fit_count',3),('optimizer_steps_per_fit',340),('initial_learning_rate',.001),
 ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('temperature',1),('selection_unchanged',False),
 ('fresh_optimizer',False),('exact_optimizer_resume',True),('boundary_atol',1e-4),('auxiliary384',None),('auxiliary768','modality.05'),
 ('inherited_plateau_scheduler_unchanged',False),('new_cohort_used_for_selection',True),('exposed_style_aggregate_already_observed_before_preregistration',False)])
def test_recipe_refuses_scope_loss_gate_or_exposure_changes(key,value):
 plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
 with pytest.raises(ValueError,match='recipe differs'):subject.validate_plan(plan)


def test_preparation_uses_old_manifest_before_only_expanding_state_authentication():
 old_manifest={'parent':'old'};new_manifest={'inputs':'new'};calls=[]
 def prepare(ctx,dimension):
  assert ctx['continuation_manifest'] is old_manifest
  calls.append(dimension);return dict(rows={'train':[1],'validation':[2]},continuation_manifest=old_manifest)
 old=SimpleNamespace(prepare_lane=prepare);ctx={'selected_runner':old,'continuation_manifest':old_manifest,'selected_manifest':new_manifest}
 lane=subject.prepare_lane(ctx,384)
 assert calls==[384] and lane['continuation_manifest'] is new_manifest
 assert ctx['continuation_manifest'] is old_manifest and lane['selected_runner'] is old
 with pytest.raises(ValueError):subject.prepare_lane(ctx,8)


@pytest.mark.parametrize('role',['selected','last-attempt'])
def test_endpoint_restore_delegates_exact_recipe_and_role(role):
 calls=[];runner=SimpleNamespace(restore_model=lambda *args:calls.append(args) or 'restored')
 lane={'selected_runner':runner};run={'states':{'selected':{'sha':'one'},'last-attempt':{'sha':'two'}},'recipe':subject.ARM}
 assert subject.restore_endpoint(lane,run,role)=='restored'
 assert calls==[(lane,run['states'][role],run['recipe'],role)]


def test_other_endpoint_role_fails_before_loader():
 with pytest.raises(ValueError):subject.restore_endpoint({}, {}, 'initial')


def test_bound_parent_artifacts_fail_closed_on_missing_or_mutated_content(tmp_path):
 p=tmp_path/'source.json';p.write_text('{"old":true}')
 manifest={'inputs':{str(p):subject.sha(p)}}
 assert subject.bound(manifest,p)=={'old':True}
 p.write_text('{"old":false}')
 with pytest.raises(ValueError):subject.bound(manifest,p)
 with pytest.raises(ValueError):subject.bound({'inputs':{}},p)


def test_no_fresh_reference_or_encoder_entry_in_driver():
 import ast
 tree=ast.parse(PATH.read_text())
 imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
 assert not any('torch' in x or 'embedding' in x or 'fresh' in x for x in imports)
 calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
 assert 'train_candidate' in calls and 'evaluate_original_panels' in calls
 assert 'generate_panel' not in calls and 'load_references' not in calls
 assert subject.FALSE['fresh_holdout'] is False and subject.FALSE['qualified'] is False
