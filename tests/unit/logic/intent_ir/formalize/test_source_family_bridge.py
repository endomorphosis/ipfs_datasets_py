"""Actual learned clauses reach existing families and context-bound typed slots."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from .test_copy_roundtrip import checkpoint
from ipfs_datasets_py.logic.intent_ir.formalize import source_family_bridge as api
from ipfs_datasets_py.logic.formalization import typed_slots
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph


def source(checkpoint):
    return checkpoint[2][1]['instruction']


def project(checkpoint, text=None, **kwargs):
    return api.project_source_intent_families(source(checkpoint) if text is None else text, checkpoint[0], **kwargs)


def slot_context(text, *, kg=False):
    context = {'schema': typed_slots.CONTEXT_SCHEMA, 'source_sha256': hashlib.sha256(text.encode()).hexdigest()}
    if not kg:
        return {**context, 'fixtures': [{'slot_id':'actor', 'sort':'Person', 'label':'illustrative actor'}]}
    graph = KnowledgeGraph('bridge-fixture')
    entity = graph.add_entity('person', 'Alice', entity_id='person:alice')
    wire = graph.to_dict()
    ref = SourceRef('source:kg', 'fixture:graph', 'graph.json', 'revision:1', typed_slots.canonical_slot_digest(wire))
    return {**context, 'knowledge_graph':wire, 'kg_bindings':[{'slot_id':'actor', 'entity_id':entity.entity_id,
        'entity_sha256':typed_slots.canonical_slot_digest(entity.to_dict()), 'source_ref':ref.to_dict()}]}


def bind(report, *, slot=None, family=None, index=0):
    return api.make_source_intent_family_context(report['document_report'], [{
        'unit_id':report['units'][index]['unit_id'], 'slot_context':slot, 'family_context':family or {}}])


def test_actual_encoder_inverse_and_source_guard_feed_existing_families(checkpoint):
    report = project(checkpoint)
    assert report['document_report']['counts']['encoder_executions'] >= 1
    assert report['document_report']['counts']['decoder_executions'] >= 1
    assert report['counts']['accepted_clauses'] == report['counts']['typed_fixtures'] == 1
    assert report['counts']['canonical_families'] == 35
    available = {row['family_id'] for row in report['family_inventory'] if row['status'] == 'available_views'}
    assert available >= {'dcec','tdfol','deontic','first_order','frame_logic','datalog','horn_chc','transition_system','higher_order','program','temporal'}
    unit = report['units'][0]
    assert unit['frame'] == checkpoint[2][1]['frame']
    assert unit['typed_fixture']['formula']['body']['predicate'] == unit['frame']['action']
    assert unit['typed_fixture']['formula']['modality'] == unit['frame']['modality']
    assert unit['typed_fixture']['status'] == 'candidate'
    assert report['training_steps'] == report['provider_calls'] == report['external_backend_calls'] == 0
    assert not report['proof_authority'] and not report['whole_document_formalized']
    assert next(p for p in unit['family_projections'] if p['family_id']=='event_calculus')['status']=='unsupported'


@pytest.mark.parametrize('kg', [False, True])
def test_explicit_person_context_specializes_fixture_without_domain_facts(checkpoint, kg):
    base = project(checkpoint)
    context = bind(base, slot=slot_context(source(checkpoint), kg=kg))
    result = project(checkpoint, context=context)
    row = result['units'][0]
    actor = row['slot_environment']['slots'][0]
    assert actor['resolved_sort'] == 'Person'
    assert actor['origin'] == ('knowledge_graph' if kg else 'fixture')
    assert row['frame'] == base['units'][0]['frame']
    assert row['candidate_intent_ir'] == base['units'][0]['candidate_intent_ir']
    assert row['family_projections'] == base['units'][0]['family_projections']
    assert 'Person' in row['typed_fixture']['carrier_map']
    assert 'Alice' not in row['typed_fixture']['lean_source']
    assert row['typed_fixture']['facts_asserted'] is row['typed_fixture']['existence_asserted'] is False


def test_repeated_clause_context_cannot_leak_to_other_source_unit(checkpoint):
    text = source(checkpoint) + '\n\n' + source(checkpoint)
    base = project(checkpoint, text)
    assert len(base['units']) == 2
    context = bind(base, slot=slot_context(source(checkpoint)))
    result = project(checkpoint, text, context=context)
    assert result['units'][0]['slot_environment']['slots'][0]['resolved_sort'] == 'Person'
    assert result['units'][1]['slot_environment']['slots'][0]['resolved_sort'] == 'Agent'
    assert result['units'][1]['context_binding'] is None


def test_explicit_temporal_and_event_premises_use_native_context_checks(checkpoint):
    base = project(checkpoint)
    family = {'modal':{'event_occurrences':[{'action_id':'action','time':7,'evidence_ref':'source'}],
        'temporal_bindings':[{'statement_id':'goal','operator':'always','evidence_ref':'source'}]}}
    result = project(checkpoint, context=bind(base, family=family))
    projections = result['units'][0]['family_projections']
    for family_id in ('dcec','tdfol'):
        modal = next(p for p in projections if p['family_id']==family_id)
        formula = modal['representation']['payload']['formulas'][0]
        assert formula['temporal_scope']['operator'] == 'always'
        assert formula['temporal_scope']['evidence_verified'] is False
        assert formula['native_parse_passed'] and formula['native_ast_roundtrip_passed']
    event = next(p for p in projections if p['family_id']=='event_calculus')
    assert event['status']=='partial'  # Normative goal is still not an observed event.
    assert event['representation']['payload']['formulas'][0]['evidence_verified'] is False
    assert 'happens' in event['representation']['source']


@pytest.mark.parametrize('change', ['source','checkpoint','candidate','clause','digest','unknown_unit'])
def test_context_exact_scope_cannot_be_resigned_away(checkpoint, change):
    report = project(checkpoint)
    context = bind(report, slot=slot_context(source(checkpoint)))
    if change=='source':context['source_sha256']='0'*64
    elif change=='checkpoint':context['checkpoint_sha256']='0'*64
    elif change=='candidate':context['units'][0]['source_ir_sha256']='0'*64
    elif change=='clause':context['units'][0]['clause_sha256']='0'*64
    elif change=='unknown_unit':context['units'][0]['unit_id']='other'
    else:context['context_sha256']='0'*64
    if change!='digest':
        context['context_sha256']=api._sha(api._wire({k:v for k,v in context.items() if k!='context_sha256'}))
    with pytest.raises(ValueError):project(checkpoint, context=context)


def test_stale_kg_refuses_fixture_without_changing_learned_meaning(checkpoint):
    base = project(checkpoint)
    stale = slot_context(source(checkpoint),kg=True)
    stale['kg_bindings'][0]['entity_sha256']='0'*64
    result = project(checkpoint, context=bind(base,slot=stale))
    unit = result['units'][0]
    assert unit['slot_environment']['status']=='unsupported' and unit['typed_fixture'] is None
    assert unit['frame']==base['units'][0]['frame'] and unit['candidate_intent_ir']==base['units'][0]['candidate_intent_ir']
    assert result['counts']['typed_fixtures']==0
    assert any(row['severity']=='error'for row in unit['slot_environment']['diagnostics'])


def test_empty_or_unsupported_source_has_no_deterministic_candidate_fallback():
    report = api.project_source_intent_families('The agent must inspect the cache.')
    assert report['status']=='fail_open_no_candidates' and report['units']==[]
    assert report['counts']['accepted_clauses']==report['counts']['typed_fixtures']==0
    assert report['counts']['canonical_families']==35


def test_contextual_example_never_becomes_projected_intent(checkpoint):
    report = project(checkpoint, '## Examples\n\n'+source(checkpoint))
    assert report['units']==[] and report['counts']['typed_fixtures']==0


@pytest.mark.parametrize('families', [['smt'],['tla_plus'],['unknown'],['higher_order','higher_order']])
def test_backend_or_profile_names_do_not_inflate_canonical_family_inventory(families):
    with pytest.raises(ValueError,match='canonical'):
        api.project_source_intent_families('Inspect cache.',requested_families=families)


def test_tampered_generated_fixture_is_rejected_before_lake(checkpoint, monkeypatch):
    report = deepcopy(project(checkpoint))
    report['units'][0]['typed_fixture']['lean_source']='axiom fabricated : False'
    report['report_sha256']=api._sha(api._wire({k:v for k,v in report.items()if k!='report_sha256'}))
    monkeypatch.setattr(typed_slots,'validate_parameterized_fixture',lambda *a,**k:pytest.fail('unreplayed artifact reached Lake'))
    with pytest.raises(ValueError,match='actual frozen inference replay'):
        api.validate_source_family_lean(report,source_text=source(checkpoint),checkpoint_descriptor=checkpoint[0],lake_executable='/missing/lake')


@pytest.mark.parametrize('kg', [False, True])
def test_actual_lake_checks_source_candidate_with_typed_person(checkpoint, kg):
    executables=sorted((Path.home()/'.elan/toolchains').glob('*/bin/lake'))
    if not executables:pytest.skip('installed native Lake required')
    base=project(checkpoint)
    report=project(checkpoint,context=bind(base,slot=slot_context(source(checkpoint),kg=kg)))
    transport={k:v for k,v in report.items()if k!='document_report'}
    receipt=api.validate_source_family_lean(transport,source_text=source(checkpoint),checkpoint_descriptor=checkpoint[0],lake_executable=str(executables[-1]))
    assert receipt['status']=='passed' and receipt['lake_attempts']==receipt['lake_passes']==1
    assert receipt['validation_inference_replays']==1 and receipt['validation_encoder_executions']>=1
    assert receipt['receipts'][0]['receipt']['claim_proved'] is False
    assert receipt['validated_scope']=='supplemental_parameterized_lean_fixture_only'
    assert receipt['other_family_backends_executed'] is receipt['claim_proved'] is False


def test_requested_only_inventory_does_not_count_unselected_native_diagnostics(checkpoint):
    report = project(checkpoint, requested_families=['temporal'])
    assert report['counts']['families_with_available_views'] == 1
    assert {r['family_id'] for r in report['family_inventory'] if r['status']=='available_views'} == {'temporal'}
    assert all(r['status']=='not_requested' for r in report['family_inventory'] if r['family_id']!='temporal')
    row=report['units'][0]
    assert len(row['native_targets']['projections']) > len(row['selected_native_targets'])
    assert report['counts']['native_targets'] == len(row['selected_native_targets'])
    assert not row['typed_fixture_available'] and report['counts']['typed_fixtures']==0


def test_typed_slot_context_requires_selected_parameterized_fixture(checkpoint):
    base=project(checkpoint)
    context=bind(base,slot=slot_context(source(checkpoint)))
    with pytest.raises(ValueError,match='higher_order'):
        project(checkpoint,context=context,requested_families=['dcec'])
