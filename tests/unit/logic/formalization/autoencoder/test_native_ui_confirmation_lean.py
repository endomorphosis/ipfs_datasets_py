"""UI confirmation semantics preserve evidence joins and real Lake counterexamples."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_confirmation_lean as ui
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as old
from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_lean as atomic

_LAKE_PATH = os.environ.get('IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE')
LAKE = Path(_LAKE_PATH).resolve() if _LAKE_PATH else None


def evidence(row, source):
    """Authored fixture declaration, not an automatic policy for unknown text."""
    items = []
    for index, formula in enumerate(row['payload']['formulas']):
        item = {'formula_index': index, 'original_formula_sha256': ui.digest(formula), 'kind': 'atomic_UI_norm'}
        if ' before ' in formula['proposition']:
            action = formula['proposition'].split('(', 1)[1].split(')', 1)[0]
            item.update(kind='UI_request_token_confirmation_policy', action_id=action,
                policy='every_invocation_has_valid_confirmation' if formula['operator'] == 'obligation' else 'unconfirmed_invocation',
                event_order='strict_sequence_position', time_domain='discrete_nat_ticks', clock_order='nondecreasing',
                max_age_ticks=5, freshness_upper_inclusive=True, correlation='action_request_token',
                cancellation='since_latest_confirmation', consumption='every_prior_invocation_consumes_token',
                trace_scope='finite_observed_prefix', unobserved_future='unknown')
        items.append(item)
    return {'schema': ui.EVIDENCE_SCHEMA, 'source_ref': source.to_dict(),
        'original_projection_id': row['projection_id'], 'original_source_digest': row['source_digest'],
        'original_payload_sha256': ui.digest(row['payload']),
        'declaration_scope': 'caller_supplied_interpretation_not_source_translation', 'formulas': items}


def case():
    src = SourceRef('source:fixture', 'urn:authored:UI-confirmation', 'fixture:UI-confirmation', 'v1',
        hashlib.sha256(b'Authored request-token confirmation policy.').hexdigest())
    formulas = [{'operator': op, 'proposition': text, 'strength': 'strict', 'source_ref_ids': [src.ref_id]}
        for op, text in [('obligation', 'confirm(publish) before invoke(publish)'),
                         ('prohibition', 'invoke(publish) before confirm(publish)'),
                         ('prohibition', 'weaken_norm(publish)')]]
    row = {'projection_id': 'ui_ux_ir:tdfol', 'source_digest': 'b' * 64, 'logic_family': 'tdfol',
           'profile': 'ui-tdfol-compilation/v1', 'payload': {'formulas': formulas}}
    return row, evidence(row, src), src


def prepare(value=None):
    row, declaration, source = value or case()
    return ui.prepare_ui_confirmation_payload(row, ui.UIConfirmationInterpretation.from_dict(declaration), expected_source_ref=source)


def test_exact_source_bound_finite_policy_keeps_no_authority():
    value = case(); before = (deepcopy(value[0]), deepcopy(value[1]), value[2])
    descriptor = prepare(value)
    code, details = ui.emit_projection(descriptor)
    assert value == before
    assert descriptor['payload']['original'] == value[0]
    assert 'uiConfirmationCheckedFormula_0' in code
    for key in ('admitted', 'capability_floor_eligible', 'source_semantics_verified',
                'source_text_inference_executed', 'runtime_authority_granted', 'event_occurrences_attested'):
        assert details[key] is False
    assert 'finite_observed' in details['semantics_scope']


def test_immutable_input_views_and_atomic_permission_retained():
    row, value, source = case()
    row['payload']['formulas'].append({'operator': 'permission', 'proposition': 'invoke(inspect)',
                                      'strength': 'weak', 'source_ref_ids': [source.ref_id]})
    value = evidence(row, source)
    frozen = ui.UIConfirmationInterpretation.from_dict(value)
    value['formulas'][0]['action_id'] = 'other'
    view = frozen.to_dict(); view['formulas'].clear()
    descriptor = ui.prepare_ui_confirmation_payload(row, frozen, expected_source_ref=source)
    code, _ = ui.emit_projection(descriptor)
    assert '"deontic:P"' in code and '"UI-strength:weak"' in code
    assert len(frozen.to_dict()['formulas']) == 4


@pytest.mark.parametrize('field,value', [
    ('original_projection_id', 'foreign'), ('original_source_digest', 'c' * 64),
    ('original_payload_sha256', 'd' * 64), ('declaration_scope', 'proven_source_semantics')])
def test_foreign_or_authoritative_bindings_rejected(field, value):
    row, declaration, source = case(); declaration[field] = value
    with pytest.raises(ValueError):
        prepare((row, declaration, source))


def test_complete_source_binding_is_required():
    row, declaration, source = case()
    declaration['source_ref']['source_revision'] = 'v2'
    with pytest.raises(ValueError, match='source_ref_differs'):
        prepare((row, declaration, source))


@pytest.mark.parametrize('mutate', ['missing', 'duplicate', 'reorder', 'formula_digest', 'source_atom', 'extra_field'])
def test_exact_formula_partition_and_closed_schema(mutate):
    row, declaration, source = case()
    if mutate == 'missing': declaration['formulas'].pop()
    if mutate == 'duplicate': declaration['formulas'][1] = deepcopy(declaration['formulas'][0])
    if mutate == 'reorder': declaration['formulas'].reverse()
    if mutate == 'formula_digest': declaration['formulas'][0]['original_formula_sha256'] = 'c' * 64
    if mutate == 'source_atom': row['payload']['formulas'][0]['proposition'] = 'confirm(erase) before invoke(erase)'
    if mutate == 'extra_field': declaration['formulas'][0]['consent_granted'] = True
    with pytest.raises(ValueError): prepare((row, declaration, source))


@pytest.mark.parametrize('field,value', [
    ('max_age_ticks', 0), ('max_age_ticks', True), ('max_age_ticks', 1000001),
    ('correlation', 'action_only'), ('event_order', 'clock_only'), ('clock_order', 'unordered'),
    ('consumption', 'unlimited'), ('cancellation', 'ignored'), ('unobserved_future', 'false'),
    ('trace_scope', 'complete_infinite_workflow'), ('freshness_upper_inclusive', 1),
    ('action_id', 'another'), ('policy', 'existential_confirmation')])
def test_unreviewed_policy_semantics_rejected(field, value):
    row, declaration, source = case(); declaration['formulas'][0][field] = value
    with pytest.raises(ValueError): prepare((row, declaration, source))


def test_opaque_original_still_blocked_and_unowned_dispatch_delegates():
    row, _, _ = case()
    with pytest.raises(ValueError, match='before_requires'): atomic.emit_projection(row)
    with pytest.raises(NotImplementedError): ui.emit_projection(row)


def test_complementary_norms_cannot_bind_same_action_to_different_windows():
    row, declaration, source = case()
    declaration['formulas'][1]['max_age_ticks'] = 10
    with pytest.raises(ValueError, match='inconsistent_UI_confirmation_policy_for_same_action'):
        prepare((row, declaration, source))


@pytest.mark.parametrize('field', ['admitted', 'source_semantics_verified', 'source_text_inference_executed'])
def test_copied_receipt_cannot_claim_authority(field):
    descriptor = prepare(); descriptor['payload'][field] = True
    with pytest.raises(ValueError, match='cannot_assert'): ui.emit_projection(descriptor)


@pytest.mark.parametrize('field,value', [('projection_id', 'other'), ('logic_family', 'fol'), ('profile', 'opaque')])
def test_descriptor_route_tampering_rejected(field, value):
    descriptor = prepare(); descriptor[field] = value
    with pytest.raises(ValueError, match='replay_differs'): ui.emit_projection(descriptor)


TOY = '''
def toy : Interpretation String String where
  agent := id
  cognitive := fun _ _ body => body
  constant := id
  function := fun _ _ => "opaque"
  atom := fun _ _ _ => False
  modal := fun op _ _ body t => if op = "deontic:F" then ¬ body t else body t
  frame := fun _ _ _ => False
  frameScalar := fun _ _ => "opaque"
  member := fun _ _ => False
  subclass := fun _ _ => False
def event (kind : UIConfirmationKind) (request token : String) (tick : Nat) : UIConfirmationEvent String :=
  ⟨kind, "publish", request, token, tick⟩
def good := [event .confirm "r1" "t1" 1, event .invoke "r1" "t1" 6]
def stale := [event .confirm "r1" "t1" 1, event .invoke "r1" "t1" 7]
def cancelled := [event .confirm "r1" "t1" 1, event .cancel "r1" "t1" 2, event .invoke "r1" "t1" 3]
def renewed := [event .confirm "r1" "t1" 1, event .cancel "r1" "t1" 2,
  event .confirm "r1" "t1" 3, event .invoke "r1" "t1" 4]
def wrongRequest := [event .confirm "r1" "t1" 1, event .invoke "r2" "t1" 2]
def wrongToken := [event .confirm "r1" "t1" 1, event .invoke "r1" "t2" 2]
def wrongAction := [{(event .confirm "r1" "t1" 1) with action := "erase"}, event .invoke "r1" "t1" 2]
def reused := [event .confirm "r1" "t1" 1, event .invoke "r1" "t1" 2, event .invoke "r1" "t1" 2]
def reconfirmedReuse := [event .confirm "r1" "t1" 1, event .invoke "r1" "t1" 2,
  event .confirm "r1" "t1" 3, event .invoke "r1" "t1" 4]
def sameTick := [event .confirm "r1" "t1" 2, event .invoke "r1" "t1" 2]
def reversed := [event .invoke "r1" "t1" 2, event .confirm "r1" "t1" 2]
def foreignCancellation := [event .confirm "r1" "t1" 1, event .cancel "r2" "t1" 2,
  event .invoke "r1" "t1" 3]
def independentRequests := [event .confirm "r1" "t1" 1, event .invoke "r1" "t1" 2,
  event .confirm "r2" "t1" 3, event .invoke "r2" "t1" 4]
def badClock := [event .confirm "r1" "t1" 1, event .invoke "r1" "t1" 2,
  event .cancel "r2" "t1" 1]
'''


def _build(path, extra):
    path.mkdir(parents=True)
    (path / 'lakefile.toml').write_text('name = "UIConfirmationChecks"\nversion = "0.1.0"\n[[lean_lib]]\nname = "UIUXIR"\n')
    tactic = 'by simp only [uiConfirmationCheckedFormula_0, uiConfirmationCheckedFormula_1, uiConfirmationCheckedFormula_2, uiConfirmationFormula_0, uiConfirmationFormula_1, uiConfirmationFormula_2, uiPrefixWellFormed, toy]; decide'
    rendered = '\n'.join(line.replace('by decide', tactic) if 'uiConfirmation' in line else line
                         for line in extra.splitlines())
    (path / 'UIUXIR.lean').write_text(old.PRELUDE + ui.emit_projection(prepare())[0] + TOY + '\n' + rendered)
    result = subprocess.run([str(LAKE), 'build', 'UIUXIR'], cwd=path, capture_output=True, text=True, timeout=60)
    (path / 'lake.stdout').write_text(result.stdout)
    (path / 'lake.stderr').write_text(result.stderr)
    (path / 'result.json').write_text(json.dumps({'command': [str(LAKE), 'build', 'UIUXIR'],
                                               'returncode': result.returncode, 'admitted': False}, indent=2))
    return result


@pytest.mark.skipif(LAKE is None, reason='Set explicit installed Lake path; tools are never downloaded')
def test_actual_lake_request_token_freshness_consumption_and_cancellation(tmp_path):
    assert LAKE.is_file(), 'Configured Lake path must exist'
    examples = ['example : uiConfirmationCheckedFormula_0 toy good 0 := by decide',
        'example : uiConfirmationCheckedFormula_1 toy good 0 := by decide',
        'example : uiConfirmationCheckedFormula_2 toy good 0 := by decide',
        'example : ¬ uiConfirmationCheckedFormula_0 toy good 1 := by decide',
        'example : ¬ uiConfirmationCheckedFormula_0 toy good 3 := by decide',
        'example : uiObservedPolicy badClock "publish" 5 0 = true := by decide',
        'example : ¬ uiConfirmationCheckedFormula_0 toy badClock 0 := by decide',
        'example : uiConfirmationCheckedFormula_0 toy [] 0 := by decide']
    for trace in ('renewed', 'sameTick', 'foreignCancellation', 'independentRequests'):
        examples.append(f'example : uiConfirmationCheckedFormula_0 toy {trace} 0 := by decide')
    for trace in ('stale', 'cancelled', 'wrongRequest', 'wrongToken', 'wrongAction', 'reused', 'reconfirmedReuse', 'reversed'):
        examples.extend([f'example : ¬ uiConfirmationCheckedFormula_0 toy {trace} 0 := by decide',
                         f'example : ¬ uiConfirmationCheckedFormula_1 toy {trace} 0 := by decide'])
    result = _build(tmp_path / 'positive-and-negated-examples', '\n' + '\n'.join(examples))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('trace', ['stale', 'cancelled', 'wrongRequest', 'reused', 'badClock'])
@pytest.mark.skipif(LAKE is None, reason='Set explicit installed Lake path; tools are never downloaded')
def test_actual_lake_rejects_false_confirmation_claims(tmp_path, trace):
    assert LAKE.is_file(), 'Configured Lake path must exist'
    result = _build(tmp_path / trace, f'\nexample : uiConfirmationCheckedFormula_0 toy {trace} 0 := by decide\n')
    assert result.returncode != 0
    assert 'error:' in result.stdout + result.stderr
    assert 'failed to synthesize' not in result.stdout + result.stderr
