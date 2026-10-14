"""Current inline action evidence takes precedence over persisted readiness."""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


SOURCE = 'The Secretary shall (except as provided in this section) publish notice.'
MARKER = 'formula_inline_exception_action_unresolved'


def cached_quality(norm):
    return replace(norm.quality, promotable_to_theorem=True, export_readiness={
        **norm.quality.export_readiness,
        'proof_ready': True, 'formula_proof_ready': True,
        'formula_requires_validation': False, 'formula_repair_required': False,
        'deterministic_resolution': {'type': 'local_scope_reference_exception'},
    })


@pytest.mark.parametrize('mutation', [
    'overlapping_action', 'wrong_action', 'missing_action_span', 'noninteger_action_span',
    'missing_modal_spans', 'conflicting_modal_alias', 'missing_exception',
    'missing_exception_span', 'missing_clause_span', 'wrong_exception_text',
    'clipped_exception_span',
])
def test_cached_clearance_cannot_replace_current_inline_source_evidence(mutation):
    element, = extract_normative_elements(SOURCE)
    norm = LegalNormIR.from_parser_element(element)
    assert build_deontic_formula_record_from_ir(norm)['proof_ready'] is True
    fields = deepcopy(norm.field_spans)
    exceptions = deepcopy(norm.exceptions)
    action = norm.action
    if mutation == 'overlapping_action':
        fields['action'][0] = norm.source_text.index('(')
    elif mutation == 'wrong_action':
        action = 'withhold notice'
    elif mutation == 'missing_action_span':
        fields.pop('action')
    elif mutation == 'noninteger_action_span':
        fields['action'] = [float(value) for value in fields['action']]
    elif mutation == 'missing_modal_spans':
        for key in ('modal', 'modality', 'deontic_operator'):
            fields.pop(key, None)
    elif mutation == 'conflicting_modal_alias':
        fields['modality'] = [fields['modal'][0] + 1, fields['modal'][1]]
    elif mutation == 'missing_exception':
        exceptions = []
    elif mutation == 'missing_exception_span':
        exceptions[0].pop('span')
    elif mutation == 'missing_clause_span':
        exceptions[0].pop('clause_span')
    elif mutation == 'wrong_exception_text':
        exceptions[0]['raw_text'] = 'as provided in some other section'
    else:
        exceptions[0]['span'][1] -= 2
        exceptions[0]['raw_text'] = norm.source_text[slice(*exceptions[0]['span'])]
    changed = replace(norm, action=action, field_spans=fields, exceptions=exceptions,
                      quality=cached_quality(norm))
    original = deepcopy(changed)
    record = build_deontic_formula_record_from_ir(changed)
    assert MARKER in record['blockers']
    assert record['proof_ready'] is False
    assert record['requires_validation'] is record['repair_required'] is True
    assert record['deterministic_resolution'] == {}
    tables = build_document_export_tables_from_ir([changed])
    for table in ('canonical', 'formal_logic', 'proof_obligations'):
        assert MARKER in tables[table][0]['blockers']
        assert tables[table][0]['proof_ready'] is False
    for table in ('decoder_reconstructions', 'prover_syntax_summaries'):
        assert tables[table][0]['proof_ready'] is False
        assert tables[table][0]['requires_validation'] is True
    assert MARKER in tables['repair_queue'][0]['reasons']
    assert changed == original


def test_stale_parser_action_span_stays_blocked_through_repeated_metric_projection():
    element, = extract_normative_elements(SOURCE)
    # Preserve a real historical failure shape: the action was clipped to the
    # introducer while its span included the whole interrupter and action.
    element['action'] = ['(except']
    element['action_verb'] = 'except'
    element['action_object'] = ''
    element['field_spans']['action'] = [element['text'].index('('), len(element['text'])]
    element['export_readiness'].update({
        'formula_proof_ready': True, 'formula_requires_validation': False,
        'formula_repair_required': False,
        'deterministic_resolution': {'type': 'local_scope_reference_exception'},
    })
    element['active_repair_required'] = False
    original = deepcopy(element)
    rows = [element]
    for _ in range(3):
        rows = parser_elements_for_metrics(rows)
        ready = rows[0]['export_readiness']
        assert MARKER in ready['formula_blockers']
        assert ready['formula_proof_ready'] is False
        assert ready['metric_repair_required'] is True
        assert ready['deterministic_resolution'] == {}
        assert rows[0]['active_repair_required'] is True
    assert element == original
