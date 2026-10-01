"""V2 gate/policy and v4 handoff accounting with explicit backend doubles.

Positive tests here replace external execution, never publish their receipts as
Lake/SANY proof. Real backend tests and the release matrix separately exercise
the installed tools. Native model preparation and source replay stay real here.
"""
from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v4 as native
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v2 as gate
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v2 as policy
from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule, CanonicalRoundTripIR
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v2 as trainer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel

FORMULAS = {'FOL':'forall x. Person(x) -> Reports(x)', 'DFOL':'forall x. O(Reports(x))',
    'TFOL':'forall x. □(Reports(x))', 'TDFOL':'forall x. O(□(Reports(x)))',
    'CEC':'K(Officer,Happens(Submit,Time))', 'DCEC':'O(K(Officer,Happens(Submit,Time)))',
    'frame_logic':'alice[role -> officer].', 'propositional':'p and q'}


def inputs(index=0):
    result={'document':CanonicalRoundTripIR((CanonicalRule('O','agent'+str(index),'submit','report'+str(index)),)),
            'source_text':'Authored gate unit fixture '+str(index)+'.'}
    source=native.supplemental_source_ref('legal_ir',**result)
    result['formula_inputs']=[NativeFormulaEvidence(key,value,source) for key,value in FORMULAS.items()]
    return result


def reviews(report):
    families={row['logic_family'] for row in report['projections']}
    return [{'family_id':name,'source_digest':report['source_digest'],'disposition':'inapplicable',
             'reason':'Closed authored unit model has no declaration for this family.',
             'evidence_refs':['unit-test:explicit-scope-not-gold']}
            for name in policy.domain_projection_policy(report['domain_id'])['family_inventory'] if name not in families]


@pytest.fixture
def fake_lake(monkeypatch):
    calls=[]
    def run(source,library,executable,seconds):
        calls.append((source,library))
        return {'status':'passed','backend_executed':True,'unit_dependency_double':True,
                'command':['unit-test-native-lake-double','build',library]}
    monkeypatch.setattr(gate,'_execute',run)
    return calls


def build(source=None, *, producer=native):
    source=source or inputs()
    method=getattr(producer,'prepare_family_training_targets_v4',None) or producer.prepare_family_training_targets_v3
    report=method('legal_ir',**source)
    handle=gate.build_native_family_lake(report,source_inputs=source,lake_executable='unit-test-only')
    observation=policy.validate_projection_report(report,lake_execution=handle,applicability_review=reviews(report))
    return report,handle,observation


def rehash(report):
    for row in report['projections']:
        row['target_sha256']=native.core._sha({k:v for k,v in row.items() if k!='target_sha256'})
    report['report_sha256']=native.core._sha({k:v for k,v in report.items() if k!='report_sha256'})


def test_v4_source_replay_checks_all_nine_projection_bindings_before_backend(fake_lake):
    report,handle,observation=build()
    receipt=gate.verify_native_family_lake(handle,report)
    assert len(receipt['per_projection'])==9 and len(fake_lake)==1
    assert all(row['lake_status']=='passed' for row in receipt['per_projection'])
    result=policy.require_projection_training_batch([observation],domain_id='legal_ir',target_reports=[report])
    assert result['strict_training_allowed'] and result['optimization_input_binding_checked']
    assert all(result[key] is False for key in policy._FALSE)
    assert receipt['execution']['unit_dependency_double'] is True


def test_coherently_rehashed_formula_tamper_fails_original_source_replay(fake_lake):
    source=inputs();report=native.prepare_family_training_targets_v4('legal_ir',**source)
    target=next(row for row in report['projections'] if row['projection_id'].endswith('/FOL/v3'))
    target['payload']['formula']='Changed(a)';rehash(report)
    with pytest.raises(ValueError):
        gate.build_native_family_lake(report,source_inputs=source,lake_executable='unit-test-only')
    assert fake_lake==[]


def test_source_mutation_after_preparation_fails_replay(fake_lake):
    source=inputs();report=native.prepare_family_training_targets_v4('legal_ir',**source)
    source['source_text']='Different source.'
    with pytest.raises(ValueError):gate.prepare_native_family_lean(report,source_inputs=source)
    assert fake_lake==[]


def test_detached_receipts_unissued_handles_and_other_report_are_rejected(fake_lake):
    report,handle,_=build()
    for item in (handle.to_dict(),gate.NativeFamilyLakeExecution(),{'status':'passed','backend_executed':True}):
        with pytest.raises(ValueError,match='live issued'):gate.verify_native_family_lake(item,report)
    with pytest.raises(ValueError,match='another report'):
        gate.verify_native_family_lake(handle,native.prepare_family_training_targets_v4('legal_ir',**inputs(3)))
    copied=handle.to_dict();copied['per_projection'][0]['parser_status']='failed'
    assert gate.verify_native_family_lake(handle,report)['per_projection'][0]['parser_status']=='passed'


def test_lake_failure_cannot_be_saved_as_positive_projection(monkeypatch):
    monkeypatch.setattr(gate,'_execute',lambda *args:{'status':'failed','backend_executed':True,'unit_dependency_double':True})
    report,handle,observation=build()
    assert all(row['lake_status']=='failed' for row in handle.to_dict()['per_projection'])
    with pytest.raises(policy.ProjectionValidationError):
        policy.require_projection_training_batch([observation],domain_id='legal_ir',target_reports=[report])


def tla_source(domain='security_ir'):
    source=panel.source_inputs(panel.rows(domain,'train')[0])
    return source,native.prepare_family_training_targets_v4(domain,**source)


@pytest.mark.parametrize('status,executed',[('blocked',False),('failed',True)])
def test_required_sany_unavailable_or_failed_blocks_parser_even_if_lake_passes(fake_lake,monkeypatch,status,executed):
    source,report=tla_source();calls=[]
    def check(requirement,**kwargs):
        calls.append(requirement)
        return {'status':status,'executed':executed,'unit_dependency_double':True}
    monkeypatch.setattr(gate,'tla',SimpleNamespace(check_sany=check))
    handle=gate.build_native_family_lake(report,source_inputs=source,lake_executable='unit-test-only')
    row=next(r for r in handle.to_dict()['per_projection'] if r['profile']=='tla_plus')
    assert calls and row['lake_status']=='passed' and row['parser_status']=='blocked'
    assert row['reason']=='required_native_syntax_checker_not_passed'
    observation=policy.validate_projection_report(report,lake_execution=handle,applicability_review=reviews(report))
    target=next(r for r in observation.to_dict()['projection_observations'] if r['profile']=='tla_plus')
    assert not target['validated'] and 'native_parser_not_passed' in target['blocking_reasons']


def test_no_local_sany_tools_never_executes_or_claims_success(fake_lake):
    source,report=tla_source()
    handle=gate.build_native_family_lake(report,source_inputs=source,lake_executable='unit-test-only')
    row=next(r for r in handle.to_dict()['per_projection'] if r['profile']=='tla_plus')
    assert row['additional_syntax_checks'][0]['executed'] is False
    assert row['parser_status']=='blocked'


def test_sany_tool_mutation_invalidates_live_evidence(fake_lake,monkeypatch,tmp_path):
    tool=tmp_path/'local-sany-tool';tool.write_bytes(b'unit dependency double, not executable')
    source,report=tla_source()
    monkeypatch.setattr(gate,'tla',SimpleNamespace(check_sany=lambda *a,**kw:{'status':'passed','executed':True,
        'unit_dependency_double':True,'tool_sha256':{str(tool):gate._sha(tool.read_bytes())}}))
    handle=gate.build_native_family_lake(report,source_inputs=source,lake_executable='unit-test-only')
    assert next(r for r in handle.to_dict()['per_projection'] if r['profile']=='tla_plus')['parser_status']=='passed'
    tool.write_bytes(b'changed unit dependency')
    with pytest.raises(ValueError,match='source provenance changed'):gate.verify_native_family_lake(handle,report)


@pytest.mark.parametrize('eligibility',[False,None,0,'false',1])
def test_false_or_nonboolean_capability_does_not_satisfy_named_floor(fake_lake,monkeypatch,eligibility):
    report,handle,_=build()
    # Deliberately modify this test-owned issuer storage to isolate the policy's
    # type boundary. This is not a supported caller path or external evidence.
    receipt=handle.to_dict()
    target=next(row for row in receipt['per_projection'] if row['projection_id'].endswith('/FOL/v3'))
    target['lowering']['capability_floor_eligible']=eligibility
    recorded=dict(gate._REGISTRY[handle]);recorded['receipt']=gate._raw(receipt)
    monkeypatch.setitem(gate._REGISTRY,handle,recorded)
    observation=policy.validate_projection_report(report,lake_execution=handle,applicability_review=reviews(report))
    assert observation.to_dict()['all_emitted_projections_validated']
    result=policy.evaluate_projection_training_batch([observation],domain_id='legal_ir',target_reports=[report])
    assert not result['modality_floor_satisfied'] and not result['strict_training_allowed']
    with pytest.raises(policy.ProjectionValidationError):
        policy.require_projection_training_batch([observation],domain_id='legal_ir',target_reports=[report])


def test_real_ui_partial_profiles_are_ineligible_for_capability_floor(fake_lake,monkeypatch):
    source,report=tla_source('ui_ux_ir')
    monkeypatch.setattr(gate,'tla',SimpleNamespace(check_sany=lambda *a,**kw:{'status':'passed','executed':True,'unit_dependency_double':True}))
    handle=gate.build_native_family_lake(report,source_inputs=source,lake_executable='unit-test-only')
    observation=policy.validate_projection_report(report,lake_execution=handle,applicability_review=reviews(report))
    rows={r['projection_id']:r for r in observation.to_dict()['projection_observations']}
    for identity in ('ui_ux_ir:event_calculus','ui_ux_ir:dcec','ui_ux_ir/event_prefix/native/v2'):
        assert rows[identity]['validated'] and not rows[identity]['capability_floor_eligible']
    result=policy.evaluate_projection_training_batch([observation],domain_id='ui_ux_ir',target_reports=[report])
    assert not result['modality_floor_satisfied']


def test_v4_strict_training_and_inference_use_live_bound_reports(fake_lake,tmp_path):
    built=[build(inputs(i)) for i in range(3)]
    observations=[row[2] for row in built]
    fitted=trainer.train_validated_family_projection_autoencoder(observations[:2],observations[2:],
        domain_id='legal_ir',output_dir=tmp_path/'checkpoint',epochs=1,latent_width=2,minibatch_size=2,denoising=0)
    result=fitted['report']
    assert result['optimizer_steps']==1 and result['training_gate_passed']
    assert result['loss_coverage']['training']['projection_occurrences']==18
    assert result['training_reports_sha256']==trainer._digest([row[0] for row in built[:2]])
    assert not result['qualified'] and not result['admitted'] and not result['source_semantics_verified']
    inferred=trainer.infer_validated_family_projection_autoencoder(fitted['descriptor'],observations[2:])
    assert inferred['loss_coverage']['projection_occurrences']==9
    assert not inferred['formulas_generated']


def test_v3_report_and_saved_observation_cannot_enter_v4_trainer(fake_lake,tmp_path):
    older=[build(inputs(i),producer=previous)[2] for i in range(2)]
    with pytest.raises(ValueError,match='exact v4'):
        trainer.train_validated_family_projection_autoencoder(older[:1],older[1:],domain_id='legal_ir',output_dir=tmp_path/'old')
    good=build()[2]
    with pytest.raises(ValueError,match='live validation observations'):
        trainer.train_validated_family_projection_autoencoder([good.to_dict()],[good.to_dict()],domain_id='legal_ir',output_dir=tmp_path/'saved')
    assert not (tmp_path/'old').exists() and not (tmp_path/'saved').exists()


def test_failed_native_gate_stops_before_optimizer_or_output(fake_lake,monkeypatch,tmp_path):
    source,report=tla_source()
    handle=gate.build_native_family_lake(report,source_inputs=source,lake_executable='unit-test-only')
    observation=policy.validate_projection_report(report,lake_execution=handle,applicability_review=reviews(report))
    monkeypatch.setattr(trainer.prepared,'_calibrate_decoder',lambda *a,**kw:pytest.fail('optimizer entered before complete gate'))
    with pytest.raises(policy.ProjectionValidationError):
        trainer.train_validated_family_projection_autoencoder([observation],[observation],domain_id=report['domain_id'],output_dir=tmp_path/'bad')
    assert not (tmp_path/'bad').exists()
