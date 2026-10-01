"""Source-replayed semantic views with explicit, optional interpretation inputs.

Intent statement roles are corrected without asserting execution. Opaque legal
or UI qualifiers remain blocked unless a caller supplies an exact interpretation
declaration. Such a declaration never establishes source fidelity or admission.
"""
from copy import deepcopy
import importlib

from . import family_training as core
from . import family_training_v4 as previous
from . import intent_semantic_training_views as intent
from . import native_qualified_lean as qualified

SCHEMA = 'domain-family-training-targets/v5'
TypedFamilyEvidence = previous.TypedFamilyEvidence
supplemental_source_ref = previous.supplemental_source_ref
ExplicitProjectionInterpretation = qualified.ExplicitProjectionInterpretation
_PINS = {name: sha for module in (core, previous, intent, qualified, importlib.import_module(__name__))
         for name, sha in core._pin(module).items()}


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        if _pin_imported_module(importlib.import_module(name)) != sha:
            raise ValueError('v5 semantic projection producer changed')


def prepare_family_training_targets_v5(domain_id, *, qualified_inputs=(), **source_inputs):
    _guard()
    if type(qualified_inputs) not in (list, tuple) or len(qualified_inputs) > 32 or any(
            type(item) is not ExplicitProjectionInterpretation for item in qualified_inputs):
        raise ValueError('bounded immutable explicit interpretation inputs required')
    base = previous.prepare_family_training_targets_v4(domain_id, **source_inputs)
    report = intent.transform(base, source_inputs)
    report.update(schema=SCHEMA, v4_report_sha256=base['report_sha256'], v4_source_digest=base['source_digest'])
    report['producer_pins'].update(_PINS)
    declarations = [item.to_dict() for item in qualified_inputs]
    identities = [row['original_projection_id'] for row in declarations]
    if len(set(identities)) != len(identities):
        raise ValueError('one explicit interpretation per original projection required')
    report['explicit_interpretation_inputs'] = deepcopy(declarations)
    report['superseded_qualified_observations'] = []
    source = supplemental_source_ref(domain_id, **source_inputs) if declarations else None
    for evidence in qualified_inputs:
        identity = evidence.to_dict()['original_projection_id']
        matches = [row for row in report['projections'] if row['projection_id'] == identity]
        if len(matches) != 1:
            raise ValueError('explicit interpretation must match one active original projection')
        original = matches[0]
        replacement = qualified.prepare_qualified_payload(original, evidence, expected_source_ref=source)
        report['producer_pins'].update(replacement.pop('producer_pins'))
        archived = deepcopy(original)
        archived.update(active_for_training=False,
            superseded_reason='explicit_caller_interpretation_added_without_source_fidelity_claim',
            replacement_projection_id=replacement['projection_id'])
        report['superseded_qualified_observations'].append(archived)
        original.update(replacement, ready_for_training=True,
            validation=[{'validator_id': 'exact_explicit_interpretation_binding', 'stage': 'target', 'status': 'passed',
                         'details': {'source_meaning_verified': False, 'Lake_executed': False}}])
    digest = core._sha({'v4_source_digest': base['source_digest'],
                       'intent_accounting': report.get('intent_semantic_replacement_accounting'),
                       'explicit_interpretation_inputs': declarations})
    report['source_digest'] = report['typed_input_digest'] = digest
    ids = [row['projection_id'] for row in report['projections']]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate semantic projection identity')
    for row in report['projections']:
        row['source_digest'] = digest
        row['target_sha256'] = core._sha({k: v for k, v in row.items() if k != 'target_sha256'})
    report['projections'].sort(key=lambda row: (row['logic_family'], row['projection_id']))
    ready = {row['logic_family'] for row in report['projections'] if row['ready_for_training']}
    for row in report['family_inventory']:
        targets = [p for p in report['projections'] if p['logic_family'] == row['family_id']]
        row.update(target_count=len(targets), ready_target_count=sum(p['ready_for_training'] for p in targets),
                   ready_for_training=row['family_id'] in ready)
        row['status'] = 'not_requested' if not row['requested'] else 'targets_available' if row['ready_for_training'] else 'unsupported'
    report['ready_for_training'] = bool(ready)
    report['all_requested_families_available'] = set(report['requested_families']) <= ready
    report['report_sha256'] = core._sha({k: v for k, v in report.items() if k != 'report_sha256'})
    validate_family_training_report_v5(report)
    return report


def validate_family_training_report_v5(report, **source_inputs):
    _guard()
    if type(report) is not dict or report.get('schema') != SCHEMA:
        raise ValueError('native v5 report required')
    if report.get('report_sha256') != core._sha({k: v for k, v in report.items() if k != 'report_sha256'}):
        raise ValueError('v5 report digest differs')
    if any(report.get('producer_pins', {}).get(name) != sha for name, sha in _PINS.items()):
        raise ValueError('v5 source producer pin differs')
    compatible = deepcopy(report)
    compatible['schema'] = core.SCHEMA
    compatible['report_sha256'] = core._sha({k: v for k, v in compatible.items() if k != 'report_sha256'})
    core.validate_family_training_report(compatible)
    if report.get('source_text_to_native_formula_inference') is not False or report.get('structural_readiness_is_qualification') is not False:
        raise ValueError('semantic target preparation cannot claim source qualification')
    if source_inputs:
        expected = prepare_family_training_targets_v5(report['domain_id'], requested_families=report['requested_families'], **source_inputs)
        if core._wire(expected) != core._wire(report):
            raise ValueError('v5 report differs from exact source and interpretation replay')
    return report
