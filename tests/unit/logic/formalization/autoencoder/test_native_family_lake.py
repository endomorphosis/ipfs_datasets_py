"""Native operator preservation and live evidence, without generic schema substitutes."""
import copy
import json
from pathlib import Path
import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake as gate
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as emit
from ipfs_datasets_py.logic.formalization.autoencoder import native_formula_evidence as formulas
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as targets
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel

FORMULAS={'FOL':'forall x. Person(x) -> Reports(x)','DFOL':'forall x. O(Reports(x))',
'TFOL':'forall x. □(Reports(x))','TDFOL':'forall x. O(□(Reports(x)))',
'CEC':'K(Officer,Happens(Submit,Time))','DCEC':'O(K(Officer,Happens(Submit,Time)))',
'frame_logic':'alice[role -> officer].','propositional':'p and q'}


def fixture(domain='legal_ir'):
    inputs=panel.source_inputs(panel.rows(domain,'train')[0])
    ref=targets.supplemental_source_ref(domain,**inputs)
    inputs['formula_inputs']=[formulas.NativeFormulaEvidence(key,value,ref) for key,value in FORMULAS.items()]
    return inputs,targets.prepare_family_training_targets_v3(domain,**inputs)


@pytest.mark.parametrize('requirement',FORMULAS)
def test_each_named_logic_lowers_actual_native_operator_tree(requirement):
    inputs=panel.source_inputs(panel.rows('legal_ir','train')[0]);ref=targets.supplemental_source_ref('legal_ir',**inputs)
    item=formulas.NativeFormulaEvidence(requirement,FORMULAS[requirement],ref)
    payload=formulas.prepare_native_formula_evidence(item,ref)['payload']
    source,observation=emit.supplied_formula(payload)
    assert source and observation['operators']
    assert 'Json' not in source and 'DecoderSchema' not in source
    expected={'FOL':'∀','DFOL':'deontic:O','TFOL':'alwaysTime','TDFOL':'alwaysTime',
              'CEC':'i.cognitive "K"','DCEC':'i.cognitive "K"','frame_logic':'i.frameScalar','propositional':'∧'}
    assert expected[requirement] in source
    if requirement in ('CEC','DCEC'): assert 'i.agent "Officer"' in source and 'Happens' in source


@pytest.mark.parametrize('requirement,formula',[('frame_logic','alice [ role -> officer ] .'),('propositional','p    and    q')])
def test_canonical_print_offsets_do_not_change_actual_AST(requirement,formula):
    inputs=panel.source_inputs(panel.rows('legal_ir','train')[0]);ref=targets.supplemental_source_ref('legal_ir',**inputs)
    payload=formulas.prepare_native_formula_evidence(formulas.NativeFormulaEvidence(requirement,formula,ref),ref)['payload']
    source,_=emit.supplied_formula(payload)
    assert source


@pytest.mark.parametrize('domain',panel.DOMAINS)
def test_all_modality_candidates_preserve_all_projection_rows_and_block_unsupported(domain):
    inputs,report=fixture(domain)
    result=gate.prepare_native_family_lean(report,source_inputs=inputs)
    assert result['library']==gate.LIBRARIES[domain]
    assert {row['projection_id'] for row in result['per_projection']}=={row['projection_id'] for row in report['projections']}
    for requirement in FORMULAS:
        row=next(x for x in result['per_projection'] if x['projection_id']==domain+'/native_formula/'+requirement+'/v3')
        assert row['parser_status']=='passed' and row['semantic_lowering_supported']
        assert row['lake_status']=='not_run'
    assert result['backend_executed'] is False and result['all_requested_projections_passed'] is False
    assert all(result[key] is False for key in gate.FALSE)
    assert result['missing_requested_families']


def test_source_replay_rejects_changed_formula_even_with_rehashed_report():
    inputs,report=fixture()
    altered=copy.deepcopy(report)
    item=next(x for x in altered['projections'] if '/native_formula/FOL/' in x['projection_id'])
    item['payload']['formula']='Changed(a)'
    item['target_sha256']=targets.core._sha({k:v for k,v in item.items() if k!='target_sha256'})
    altered['report_sha256']=targets.core._sha({k:v for k,v in altered.items() if k!='report_sha256'})
    with pytest.raises(ValueError): gate.prepare_native_family_lean(altered,source_inputs=inputs)


def test_original_typed_inputs_required():
    _,report=fixture()
    with pytest.raises(ValueError,match='original typed source'): gate.prepare_native_family_lean(report,source_inputs={})


def test_archived_dict_and_unissued_handle_cannot_be_used_as_execution():
    _,report=fixture()
    for fake in ({'backend_executed':True,'status':'passed'},gate.NativeFamilyLakeExecution()):
        with pytest.raises(ValueError,match='live issued'): gate.verify_native_family_lake(fake,report)


def test_missing_lake_is_live_failure_not_qualification(tmp_path):
    inputs,report=fixture()
    result=gate.build_native_family_lake(report,source_inputs=inputs,lake_executable='/absent/native/lake',output_directory=tmp_path/'output')
    receipt=gate.verify_native_family_lake(result,report)
    assert not receipt['backend_executed'] and receipt['status']=='unavailable'
    assert not receipt['all_requested_projections_passed']
    copied=receipt.copy();copied['status']='passed'
    with pytest.raises(ValueError,match='live issued'): gate.verify_native_family_lake(copied,report)
    other=copy.deepcopy(report);other['extra']=1
    with pytest.raises(ValueError): gate.verify_native_family_lake(result,other)


def test_unsupported_annotations_are_not_erased():
    renderer=emit.FormulaRenderer()
    with pytest.raises(emit.UnsupportedNativeLean,match='time_annotation'):
        renderer.formula({'node_type':'TemporalFormula','operator':{'value':'□'},'time_bound':10,'formula':{}})
    with pytest.raises(emit.UnsupportedNativeLean,match='unsupported_native_formula'):
        renderer.formula({'node_type':'OpaqueFormula','text':'P until Q'})


def test_tla_artifact_cannot_borrow_native_state_only_gate():
    with pytest.raises(emit.UnsupportedNativeLean,match='TLA_artifact'):
        emit.emit_projection({'projection_id':'security_ir/transition/tla_plus/v3','logic_family':'transition_system',
            'payload':{'native_document':{'schema_version':'state-transition-ir/v1'},'artifact':{'model_text':'raw'}}})


def _state(reads=('var:x',),cardinality=None,kind='integer'):
    from ipfs_datasets_py.logic.software_verification.state import StateSchema,StateVariable,FiniteDomainBound,StatePredicate
    from ipfs_datasets_py.logic.software_verification.transitions import StateTransitionIR,Action,ActionFrame,TransitionRelation
    bound=FiniteDomainBound('bound:x',lower=0 if kind=='integer' else None,upper=1 if kind=='integer' else None,cardinality=cardinality)
    schema=StateSchema(variables=(StateVariable('var:x','x',kind,boundedness='finite',domain_bound=bound),))
    a,b=(0,1) if kind=='integer' else (False,True)
    predicates=tuple(StatePredicate(name,role,expression={'x':value},statement=name,subject_variable_ids=('var:x',))
                     for name,role,value in [('initial','initial',a),('guard','guard',a),('next','next',b)])
    action=Action('action:set','Set',ActionFrame(reads=reads,writes=('var:x',)),guard_predicate_id='guard',next_predicate_id='next')
    return StateTransitionIR(schema=schema,predicates=predicates,actions=(action,),transitions=(
        TransitionRelation('relation:set','action','Set',action_ids=('action:set',)),)).to_dict()


def test_guard_read_frame_is_checked_and_emitted_as_actual_finite_contract():
    source,_=emit.state_document(_state())
    assert 'def readFrame_0' in source and '.all readFrame_0 = true := by decide' in source
    with pytest.raises(emit.UnsupportedNativeLean,match='guard_reads_outside'):
        emit.state_document(_state(reads=()))


def test_finite_cardinality_cannot_be_silently_erased():
    with pytest.raises(emit.UnsupportedNativeLean,match='cardinality'):
        emit.state_document(_state(cardinality=1))
    source,_=emit.state_document(_state(cardinality=2,kind='boolean'))
    assert 'v0 : Bool' in source
    with pytest.raises(emit.UnsupportedNativeLean,match='cardinality'):
        emit.state_document(_state(cardinality=1,kind='boolean'))


def test_frame_string_and_constant_are_distinct_interpretation_symbols():
    inputs=panel.source_inputs(panel.rows('legal_ir','train')[0]);ref=targets.supplemental_source_ref('legal_ir',**inputs)
    def lower(text):
        item=formulas.NativeFormulaEvidence('frame_logic',text,ref)
        return emit.supplied_formula(formulas.prepare_native_formula_evidence(item,ref)['payload'])[0]
    assert lower('a[p -> foo].')!=lower('a[p -> "foo"].')


@pytest.mark.parametrize('modality',['O','P','F'])
def test_unqualified_canonical_norm_preserves_modality_actor_action_object(modality):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule,CanonicalRoundTripIR
    value=CanonicalRoundTripIR((CanonicalRule(modality,'agency','submit','report'),)).to_dict()
    source,observation=emit.canonical_norms(value)
    assert 'deontic:'+modality in source and 'i.constant "agency"' in source and 'i.constant "report"' in source
    assert 'i.atom "submit"' in source and observation['rule_count']==1


@pytest.mark.parametrize('field',['conditions','exceptions','temporal'])
def test_canonical_qualifiers_block_instead_of_disappearing(field):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule,CanonicalRoundTripIR
    value=CanonicalRoundTripIR((CanonicalRule('O','agency','submit','report',**{field:('qualified',)}),)).to_dict()
    with pytest.raises(emit.UnsupportedNativeLean,match='qualified_canonical_rule'):
        emit.canonical_norms(value)


def test_canonical_empty_object_arity_and_repeated_rules_preserved():
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule,CanonicalRoundTripIR
    rule=CanonicalRule('O','agency','notify','')
    source,observation=emit.canonical_norms(CanonicalRoundTripIR((rule,rule)).to_dict())
    assert observation['rule_count']==2 and source.count('def norm_')==2
    assert '[(i.constant "agency")]' in source and 'i.constant ""' not in source


@pytest.mark.parametrize('kind,cardinality',[('integer',None),('boolean',2)])
def test_actual_native_lake_checks_state_read_frame_contract(kind,cardinality):
    candidates=sorted((Path.home()/'.elan'/'toolchains').glob('*/bin/lake'))
    if not candidates: pytest.skip('No installed native Lake available; no download attempted')
    source,_=emit.state_document(_state(kind=kind,cardinality=cardinality))
    lean='namespace SecurityIR\n'+emit.PRELUDE+'\n'+source+'\nend SecurityIR\n'
    execution=gate._execute(lean,'SecurityIR',candidates[-1],30)
    assert execution['backend_executed'] is True
    assert execution['status']=='passed',execution
    assert execution['command'][-2:]==['build','SecurityIR']
