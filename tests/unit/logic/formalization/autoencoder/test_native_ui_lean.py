"""UI lowering semantics and fail-closed boundaries; real Lake opt-in below."""
from copy import deepcopy
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_lean as ui
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as native
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as old
from ipfs_datasets_py.logic.software_verification.trace import (
    TraceIR, Clock, ClockDomain, TimeUnit, TimeValue, TimePoint, Event, ObservationPolicy, ObservationPolicyKind, TraceKind)
from ipfs_datasets_py.logic.software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel


@pytest.fixture(scope='module')
def rows():
    inputs = panel.source_inputs(panel.rows('ui_ux_ir', 'train')[0])
    report = native.prepare_family_training_targets_v3('ui_ux_ir', **inputs)
    return {r['projection_id']: r for r in report['projections']}


def prefix(policy='explicit', *, kind='finite_prefix'):
    clocks = (Clock('clock:test', ClockDomain.DENSE, TimeUnit.SECOND, TimeValue(1, 2)),)
    events = (Event('event:one', 'activate', TimePoint('clock:test', TimeValue(1, 2)), ('p',), ('f',)),
              Event('event:two', 'focus', TimePoint('clock:test', TimeValue(1, 2))))
    native = TraceIR(clocks, events, TraceKind(kind), ObservationPolicy('policy:test', ObservationPolicyKind(policy),
        ('visible',) if policy == 'projected' else ()), 'clock:test')
    bridge = SoftwareVerificationSyntaxBridge().round_trip(native).to_dict()
    return {'native_document':native.to_dict(), 'typed_expression':bridge['expression'], 'bridge':bridge}


def test_matrix_owned_routes_lower_without_changing_input(rows):
    expected = ('interface_bindings', 'dcec', 'event_calculus')
    for name in expected:
        row = rows['ui_ux_ir:' + name]
        before = deepcopy(row)
        source, details = ui.emit_projection(row)
        assert source and row == before
        assert details['source_semantics_verified'] is False
        assert details['runtime_authority_granted'] is False
    source, details = ui.emit_projection(rows['ui_ux_ir/event_prefix/native/v2'])
    assert 'def observation' in source and details['future_observation'] == 'unknown'


def test_unowned_route_delegates_and_owned_identity_mismatch_blocks(rows):
    with pytest.raises(NotImplementedError): ui.emit_projection({'projection_id':'other'})
    row = deepcopy(rows['ui_ux_ir:dcec']); row['logic_family'] = 'first_order'
    with pytest.raises(old.UnsupportedNativeLean, match='route_identity'): ui.emit_projection(row)


def test_cognition_keeps_actor_and_speculative_content_distinct():
    payload = {'formulas':[{'kind':'believes','actor':'user:one','content':'not_auto_intent(event:one)','source_ref_ids':[]},
                           {'kind':'intends','actor':'user:two','content':'maybe_intent(event:two)','source_ref_ids':[]}]}
    source,details = ui.cognitive(payload)
    assert 'i.cognitive "believes" (i.agent "user:one")' in source
    assert 'i.cognitive "intends" (i.agent "user:two")' in source
    assert 'i.atom "not_auto_intent"' in source and 'i.atom "maybe_intent"' in source
    assert not details['capability_floor_eligible']
    assert not details['event_occurrences_attested']


@pytest.mark.parametrize('content', ['p and q','activate(x) before confirm(x)','not activate(x)','f(g(x))','f(x,y)','f(x) trailing'])
def test_opaque_cognitive_content_does_not_become_atomic(content):
    with pytest.raises(old.UnsupportedNativeLean, match='single_explicit_atom'):
        ui.cognitive({'formulas':[{'kind':'observes','actor':'user','content':content,'source_ref_ids':[]}]})


def test_tdfol_before_remains_blocked(rows):
    with pytest.raises(old.UnsupportedNativeLean, match='precedence_semantics'):
        ui.emit_projection(rows['ui_ux_ir:tdfol'])


def test_atomic_norm_retains_modality_and_strength_without_temporal_claim():
    source,details = ui.deontic({'formulas':[{'operator':'permission','proposition':'invoke(save)',
        'strength':'weak','source_ref_ids':['source:one']}]})
    assert 'i.modal "deontic:P" [] (some "UI-strength:weak")' in source
    assert 'i.atom "invoke"' in source and 'source:one' in source
    assert not details['capability_floor_eligible']


def test_ec_is_declared_edge_not_timed_occurrence(rows):
    source,details = ui.emit_projection(rows['ui_ux_ir:event_calculus'])
    assert 'def step (event beforeState afterState' in source
    assert '("event:activate", "pending", "finished")' in source
    assert 'theorem declared_edge_0' in source
    assert not details['capability_floor_eligible']
    assert 'Happens' not in source and 'Nat' not in source


@pytest.mark.parametrize('change', ['timeout','multi_source','unknown_state','effect_mismatch'])
def test_ec_ambiguity_or_effect_mismatch_blocks(rows, change):
    payload = deepcopy(rows['ui_ux_ir:event_calculus']['payload'])
    edge = next(r for r in payload['formulas'] if r['kind']=='happens')
    if change == 'timeout': edge['args'] = ['timeout(tr:one)', '1000']
    elif change == 'multi_source': edge['args'].insert(1,'parallel')
    elif change == 'unknown_state': edge['args'][1] = 'unknown'
    else: next(r for r in payload['formulas'] if r['kind']=='initiates')['args'][1]='in_state(pending)'
    with pytest.raises(old.UnsupportedNativeLean): ui.declared_edges(payload)


def test_interface_has_typed_requests_results_and_binding_predicate(rows):
    source,details = ui.emit_projection(rows['ui_ux_ir:interface_bindings'])
    assert 'structure Input0 where\n  f0 : String' in source
    assert 'structure Output0 where\n  f0 : Bool' in source
    assert 'invoke : Input0 → Output0 → Prop' in source
    assert 'def boundInvocation0' in source and 'def bindingMatches0' in source
    assert '"non_idempotent"' in source and '"confirm"' in source
    assert details['field_mapping'][0]['source_field']=='record_id'
    assert not details['runtime_authority_granted']


def test_optional_nested_interface_fields_are_distinct_from_absent(rows):
    payload=deepcopy(rows['ui_ux_ir:interface_bindings']['payload'])
    payload['bindings'][0]['method_contract']['input_schema']={'type':'object','properties':{
        'records':{'type':'array','items':{'type':'object','properties':{'value':{'type':'integer'}},
        'required':['value'],'additionalProperties':False}}},'required':[],'additionalProperties':False}
    source,_=ui.interface_bindings(payload)
    assert 'Option (List (Input0Field0Item))' in source
    assert 'f0 : Int' in source


@pytest.mark.parametrize('change', ['extra_property','pattern','wrong_cid','wrong_method','duplicate_action','unknown_binding_field'])
def test_interface_unsupported_constraints_or_inconsistent_joins_block(rows,change):
    payload=deepcopy(rows['ui_ux_ir:interface_bindings']['payload']); binding=payload['bindings'][0]
    if change=='extra_property': binding['method_contract']['input_schema']['additionalProperties']=True
    elif change=='pattern': binding['method_contract']['input_schema']['properties']['record_id']['pattern']='.*'
    elif change=='wrong_cid': binding['interface_cid']='wrong'
    elif change=='wrong_method': binding['method_contract']['name']='different'
    elif change=='duplicate_action': payload['bindings'].append(deepcopy(binding))
    else: binding['inferred_authority']=True
    with pytest.raises(old.UnsupportedNativeLean): ui.interface_bindings(payload)


@pytest.mark.parametrize('kind', ['explicit','closed_world','projected'])
def test_prefix_keeps_actual_native_observation_policy_and_unknown_future(kind):
    payload=prefix(kind); source,details=ui.trace_prefix(payload)
    assert 'denominator := 2' in source and 'unit := "second"' in source
    assert source.index('identifier := "event:one"') < source.index('identifier := "event:two"')
    assert '| none => none' in source
    assert 'def observationPolicy : String := "'+kind+'"' in source
    assert details['future_observation']=='unknown' and not details['capability_floor_eligible']
    assert 'theorem boundary_is_unknown' in source
    if kind=='projected': assert 'if atom ∈ visibleAtoms then some false else none' in source
    if kind=='explicit': assert 'else none' in source


def test_prefix_rejects_complete_trace_and_altered_bridge():
    with pytest.raises(old.UnsupportedNativeLean,match='incomplete_finite_prefix'):
        ui.trace_prefix(prefix(kind='finite'))
    payload=prefix();payload['bridge']['exact']=False
    with pytest.raises(old.UnsupportedNativeLean,match='bridge_replay_differs'): ui.trace_prefix(payload)


def test_real_lake_ui_contracts_and_observation_oracles(rows,tmp_path):
    executable=os.environ.get('IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE')
    if not executable: pytest.skip('explicit installed native Lake binary required; no download')
    assert Path(executable).is_absolute() and Path(executable).is_file()
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
    blocks=[old.PRELUDE]
    for index,name in enumerate(('interface_bindings','dcec','event_calculus')):
        source,_=ui.emit_projection(rows['ui_ux_ir:'+name]);blocks.append(f'namespace Case{index}\n'+source+f'\nend Case{index}')
    for kind in ('explicit','closed_world','projected'):
        source,_=ui.trace_prefix(prefix(kind))
        blocks.append('namespace '+kind+'\n'+source)
        native=TraceIR.from_dict(prefix(kind)['native_document'])
        for pos in range(2):
            for atom in ('p','f','visible','unknown'):
                expected={'true':'some true','false':'some false','unknown':'none'}[native.observe(pos,atom).value]
                blocks.append(f'example : observation {pos} "{atom}" = {expected} := by decide')
        blocks += ['example : observation 20 "p" = none := by decide','end '+kind]
    result=_execute('\n\n'.join(blocks),'UIContracts',executable,60)
    (tmp_path/'execution.json').write_text(__import__('json').dumps(result,indent=2))
    assert result['backend_executed'] and result['status']=='passed',result


def test_real_lake_does_not_prove_closed_world_beyond_prefix(tmp_path):
    executable=os.environ.get('IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE')
    if not executable: pytest.skip('explicit installed native Lake binary required; no download')
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
    source,_=ui.trace_prefix(prefix('closed_world'))
    source+='\nexample : observation 2 "p" = some false := by decide\n'
    result=_execute(source,'UIInvalidFuture',executable,60)
    (tmp_path/'intentional-negative-execution.json').write_text(__import__('json').dumps(result,indent=2))
    assert result['backend_executed'] and result['status']=='failed'
    assert not result['timed_out']
