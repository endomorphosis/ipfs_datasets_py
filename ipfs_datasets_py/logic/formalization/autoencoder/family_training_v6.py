"""Explicit guarded Intent targets with exhaustive native effect joins.

The caller supplies finite abstract guard/update/effect interpretations. Neither
target preparation nor a successful native build establishes source fidelity.
Missing declarations leave the previous unsupported projections in place.
"""
from copy import deepcopy
import importlib

from . import family_training as core
from . import family_training_v5 as previous
from . import native_intent_guarded_lean as guarded
from ...intent_ir.formalize import state_projections

SCHEMA = 'domain-family-training-targets/v6'
TypedFamilyEvidence = previous.TypedFamilyEvidence
ExplicitProjectionInterpretation = previous.ExplicitProjectionInterpretation
IntentEffectBindings = guarded.IntentEffectBindings
supplemental_source_ref = previous.supplemental_source_ref
_PINS = {name: sha for module in (core, previous, guarded, state_projections,
         importlib.import_module(__name__)) for name, sha in core._pin(module).items()}
_REPLACED = {
    'intent-route/workflow-temporal/v1': ('workflow', 'temporal', 'guarded_intent_workflow/v1'),
    'intent-extended/transition_system/default/v1': ('state', 'transition_system', 'guarded_intent_state/v1'),
    'intent-extended/transition_system/tla_plus/v1': ('tla_plus', 'transition_system', 'tla_plus'),
}


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        if _pin_imported_module(importlib.import_module(name)) != sha:
            raise ValueError('v6 guarded target producer changed')


def prepare_family_training_targets_v6(domain_id, *, guarded_effect_bindings=None, **source_inputs):
    _guard()
    if guarded_effect_bindings is not None and (
            domain_id != 'intent_ir' or type(guarded_effect_bindings) is not IntentEffectBindings):
        raise ValueError('immutable guarded effect bindings require IntentIR')
    base = previous.prepare_family_training_targets_v5(domain_id, **source_inputs)
    report = deepcopy(base)
    report.update(schema=SCHEMA, v5_report_sha256=base['report_sha256'], v5_source_digest=base['source_digest'],
                  guarded_effect_binding_input=None, superseded_guarded_observations=[])
    report['producer_pins'].update(_PINS)
    if guarded_effect_bindings is not None:
        if not {'program', 'temporal', 'transition_system'} <= set(report['requested_families']):
            raise ValueError('guarded source requires all contract, workflow and state families')
        document, context = source_inputs.get('document'), source_inputs.get('context')
        payload = guarded.prepare_guarded_payload(document, context, guarded_effect_bindings)
        report['producer_pins'].update(guarded.producer_pins())
        report['guarded_effect_binding_input'] = guarded_effect_bindings.to_dict()
        native_rows = state_projections.project_state_families(document, context)
        expected = {row['projection_id']: row['representation'] for row in native_rows}
        for identity in _REPLACED:
            rows = [p for p in report['projections'] if p['projection_id'] == identity]
            if len(rows) != 1:
                raise ValueError('guarded replacement requires every exact original native projection')
            if identity != 'intent-route/workflow-temporal/v1' and (
                    identity not in expected or rows[0]['payload'] != expected[identity]):
                raise ValueError('guarded replacement differs from original native state projection')
        ready = payload['ready_for_training']
        if type(ready) is not bool:
            raise ValueError('native guarded readiness must be explicit')
        validation = [{'validator_id': 'exhaustive_guarded_source_effect_replay', 'stage': 'target',
            'status': 'passed' if ready else 'failed',
            'details': {'native_all_outcomes_checked': True, 'source_semantics_verified': False,
                        'Lake_executed': False, 'complete_training_contract_satisfied': ready}}]
        gaps = ['caller_supplied_finite_interpretations', 'source_semantics_not_verified',
                'actual_execution_not_attested', 'bounded_state_space', 'Lake_and_SANY_must_execute']
        for original in report['projections']:
            identity = original['projection_id']
            if identity not in _REPLACED:
                continue
            route, family, profile = _REPLACED[identity]
            replacement_id = 'intent_ir/guarded/' + route + '/v1'
            archived = deepcopy(original)
            archived.update(active_for_training=False, replacement_projection_id=replacement_id,
                superseded_reason='exact_guarded_native_model_with_explicit_effect_bindings')
            report['superseded_guarded_observations'].append(archived)
            original.update(projection_id=replacement_id, logic_family=family, profile=profile,
                producer_id=guarded.__name__, payload=deepcopy(payload), validation=deepcopy(validation),
                qualification_gaps=list(gaps), ready_for_training=ready)
        report['projections'].append({'projection_id': 'intent_ir/guarded/action_contract/v1',
            'logic_family': 'program', 'profile': 'guarded_intent_action_contract/v1',
            'representation_kind': 'native_typed_projection', 'producer_id': guarded.__name__,
            'payload': deepcopy(payload), 'validation': deepcopy(validation),
            'qualification_gaps': list(gaps), 'ready_for_training': ready,
            'source_digest': base['source_digest'], **core.AUTHORITY})
        if not ready:
            report['frontier'].append({'family_id': 'transition_system',
                'reason': 'guarded_deadlock_or_unverified_or_failed_effect_contract',
                'projection_ids': ['intent_ir/guarded/' + r + '/v1'
                                   for r in ('state', 'workflow', 'action_contract', 'tla_plus')]})
    digest = core._sha({'v5_source_digest': base['source_digest'],
                       'guarded_effect_binding_input': report['guarded_effect_binding_input']})
    report['source_digest'] = report['typed_input_digest'] = digest
    identities = [row['projection_id'] for row in report['projections']]
    if len(identities) != len(set(identities)):
        raise ValueError('duplicate guarded projection identity')
    for row in report['projections']:
        row['source_digest'] = digest
        row['target_sha256'] = core._sha({k: v for k, v in row.items() if k != 'target_sha256'})
    report['projections'].sort(key=lambda row: (row['logic_family'], row['projection_id']))
    ready_families = {r['logic_family'] for r in report['projections'] if r['ready_for_training']}
    for row in report['family_inventory']:
        targets = [p for p in report['projections'] if p['logic_family'] == row['family_id']]
        row.update(target_count=len(targets), ready_target_count=sum(p['ready_for_training'] for p in targets),
                   ready_for_training=row['family_id'] in ready_families)
        row['status'] = ('not_requested' if not row['requested'] else
                         'targets_available' if row['ready_for_training'] else 'unsupported')
    report['ready_for_training'] = bool(ready_families)
    report['all_requested_families_available'] = set(report['requested_families']) <= ready_families
    report['report_sha256'] = core._sha({k: v for k, v in report.items() if k != 'report_sha256'})
    validate_family_training_report_v6(report)
    return report


def validate_family_training_report_v6(report, **source_inputs):
    _guard()
    if type(report) is not dict or report.get('schema') != SCHEMA:
        raise ValueError('native v6 report required')
    if report.get('report_sha256') != core._sha({k: v for k, v in report.items() if k != 'report_sha256'}):
        raise ValueError('v6 report digest differs')
    if any(report.get('producer_pins', {}).get(name) != sha for name, sha in _PINS.items()):
        raise ValueError('v6 producer pin differs')
    compatible = deepcopy(report)
    compatible['schema'] = core.SCHEMA
    compatible['report_sha256'] = core._sha({k: v for k, v in compatible.items() if k != 'report_sha256'})
    core.validate_family_training_report(compatible)
    if report.get('source_text_to_native_formula_inference') is not False or report.get('structural_readiness_is_qualification') is not False:
        raise ValueError('guarded target preparation cannot claim source qualification')
    if source_inputs:
        inputs = dict(source_inputs)
        requested = inputs.pop('requested_families', report['requested_families'])
        if list(requested) != report['requested_families']:
            raise ValueError('v6 replay family request differs')
        expected = prepare_family_training_targets_v6(report['domain_id'],
            requested_families=report['requested_families'], **inputs)
        if core._wire(expected) != core._wire(report):
            raise ValueError('v6 report differs from exact source, context and effect replay')
    return report
