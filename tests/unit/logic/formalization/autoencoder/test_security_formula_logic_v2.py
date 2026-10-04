"""Typed source semantics, native projections, learned inference and actual Lake."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_logic_v2 as api
from .test_security_formula_decoder_v2 import expanded_checkpoint, parent_checkpoint


def function(body, args='value, other'):
    return ('def control(' + args + '):\n' + ''.join('    ' + line + '\n' for line in body.split('\n'))).encode()


@pytest.mark.parametrize('body,sort,op', [
    ('return value + 2', 'Int', 'add'),
    ('return value * 3', 'Int', 'mul'),
    ('return -value', 'Int', 'neg'),
    ('return not value', 'Bool', 'not'),
    ('return value and other', 'Bool', 'and'),
    ('return value or other', 'Bool', 'or'),
    ('return value == other', 'Bool', 'eq'),
    ('return value != 0', 'Bool', 'ne'),
    ('return value <= 0', 'Bool', 'le'),
    ('return value >= 0', 'Bool', 'ge'),
    ('return value > 0', 'Bool', 'gt'),
    ('return True', 'Bool', 'literal'),
    ('return False', 'Bool', 'literal'),
    ('return None', 'Unit', 'literal'),
    ('return "λ"', 'String', 'literal'),
    ('return 1 if value else 0', 'Int', 'if'),
    ('if value < 0:\n    return 0\nreturn value', 'Int', 'if'),
    ('if value:\n    local = 2\n    return local\nelse:\n    return 3', 'Int', 'if'),
])
def test_independent_typed_lowering_and_exact_native_program_contract(body, sort, op):
    raw = function(body)
    model = api.lower_pure_function_v2(raw)
    assert model.result.sort == sort and model.result.op == op
    projections = api._native_projections(model, raw, 'control.py')
    assert [(p['family_id'], p['profile_id']) for p in projections] == [('program', 'program_ir'), ('program', 'dynamic_hoare')]
    assert all(p['bridge']['preservation'] == 'exact' for p in projections)
    assert not any(p['proof_authority'] or p['source_runtime_semantics_verified'] for p in projections)


@pytest.mark.parametrize('body', [
    'return str(value)', 'return value / 2', 'return 1.2', 'return [value]',
    'return value is None', 'return value < other < 10', 'return value + True',
    'return value + 1 if value else False', 'return "a" + "b"', 'return missing',
    'value = 2\nreturn value', 'if value:\n    return 1',
    'return 1\nreturn 2', 'if value:\n    return 1\nelse:\n    return 2\nreturn 3',
    'if value:\n    local = 1\nreturn local', 'return "\\ud800"',
])
def test_unsupported_semantics_never_become_typed_models(body):
    with pytest.raises(api.UnsupportedLogic):
        api.lower_pure_function_v2(function(body))


def test_branch_conditions_constrain_bool_and_arithmetic_constrains_int():
    model = api.lower_pure_function_v2(function('return other + 1 if value else other - 1'))
    assert [p[2] for p in model.parameters] == ['Bool', 'Int']
    smt = api._smt_projection(model, model)
    assert smt['family_id'] == 'smt' and not smt['solver_executed']
    assert 'forall' in str(smt['compilation']) and 'ite' in str(smt['compilation'])


def test_unused_self_is_polymorphic_and_none_is_unit():
    model = api.lower_pure_function_v2(function('return None', args='self'))
    assert model.parameters == (('self', 'p0', 'opaque'),)
    assert model.result.sort == 'Unit'
    assert '{T0 : Type} (p0 : T0) : Unit' in api._render_lean(model, model)
    with pytest.raises(api.UnsupportedLogic, match='smt_scalar_route'):
        api._smt_projection(model, model)


def test_alias_expansion_budget_checked_before_exponential_allocation():
    lines = ['v0 = value + value'] + ['v'+str(i)+' = v'+str(i-1)+' + v'+str(i-1) for i in range(1, 31)] + ['return v30']
    with pytest.raises(api.UnsupportedLogic, match='expanded_expression_bound'):
        api.lower_pure_function_v2(function('\n'.join(lines)))


def test_typed_expression_and_parameter_scope_are_checked():
    with pytest.raises(api.UnsupportedLogic):
        api.PureExpression('literal', 'Int', value=True)
    with pytest.raises(api.UnsupportedLogic):
        api.PureFunction((('value','p0','Int'),), api.PureExpression('parameter', 'Bool', value='p0'))


def test_derived_result_contract_does_not_invent_security_requirement():
    raw = function('if value < 0:\n    return 0\nreturn value')
    model = api.lower_pure_function_v2(raw)
    projections = api._native_projections(model, raw, 'example.py')
    contract = projections[1]['native_document']
    assert contract['attributes']['role'] == 'derived_model_result_equation'
    assert not contract['attributes']['security_specification_inferred']
    assert len(contract['postconditions']) == 1
    assert not contract['preconditions'] and not contract['exceptional_postconditions']


@pytest.mark.parametrize('body', [
    'return value < 0',
    'if value < 0:\n    return 0\nreturn value',
    'return 1 if value else 0',
    'return None',
    'return value and other',
])
def test_real_weights_generate_typed_ir_and_logic_projections(expanded_checkpoint, body):
    raw = function(body)
    report = api.project_security_formula_logic_v2(source_bytes=raw, checkpoint=expanded_checkpoint, source_path='control.py')
    assert report['status'] == 'candidate', report['frontiers']
    assert report['decode']['predicted_productions'] and report['decode']['validation']['source_AST_equivalent']
    assert report['typed_ir'] == report['source_typed_ir']
    assert report['learned_equation_count'] == 1 and report['model_equality_verified']
    assert len(report['projections']) >= 2
    assert not report['proof_authority'] and not report['security_specification_inferred']
    assert 'predicted_matches_source_model' in report['lean_source']
    assert 'predicted_satisfies_result_contract' in report['lean_source']
    assert 'sorry' not in report['lean_source'] and 'axiom' not in report['lean_source']


@pytest.mark.parametrize('body', [
    'if value < 0:\n    return 0\nreturn value',
    'return 1 if value else 0',
    'return None',
    'return value and other',
    'return "safe"',
])
def test_real_lake_builds_typed_models_and_result_contract(expanded_checkpoint, body):
    lakes = sorted((Path.home()/'.elan'/'toolchains').glob('*/bin/lake'))
    if not lakes:
        pytest.skip('installed native Lake toolchain unavailable')
    raw = function(body)
    report = api.project_security_formula_logic_v2(source_bytes=raw, checkpoint=expanded_checkpoint, source_path='control.py')
    receipt = api.validate_security_formula_logic_v2(report, source_bytes=raw, checkpoint=expanded_checkpoint, lake_executable=lakes[-1])
    assert receipt['status'] == 'passed', (report['frontiers'], receipt)
    assert receipt['backend_executed'] and receipt['model_equality_proved'] and receipt['derived_result_contract_proved']
    assert receipt['source_runtime_semantics_verified'] is False


@pytest.mark.parametrize('options', [{'model_enabled': False}, {'weight_ablation': 'zero_production_heads'}])
def test_disabled_model_or_ablated_heads_never_use_static_fallback(expanded_checkpoint, options):
    raw = function('return value < 0')
    report = api.project_security_formula_logic_v2(source_bytes=raw, checkpoint=expanded_checkpoint, source_path='control.py', **options)
    assert report['status'] == 'unsupported' and report['typed_ir'] is None and report['projections'] == []
    assert report['lean_source'] is None and report['learned_equation_count'] == 0


@pytest.mark.parametrize('field', ['lean', 'typed_ir', 'projections', 'hash'])
def test_modified_projection_rejected_before_lake(expanded_checkpoint, monkeypatch, field):
    from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
    raw = function('return value < 0')
    report = deepcopy(api.project_security_formula_logic_v2(source_bytes=raw, checkpoint=expanded_checkpoint, source_path='control.py'))
    assert report['status'] == 'candidate'
    if field == 'lean': report['lean_source'] += '\naxiom wrong : False\n'
    elif field == 'typed_ir': report['typed_ir']['result_sort'] = 'String'
    elif field == 'projections': report['projections'][0]['family_id'] = 'temporal'
    else: report['projection_sha256'] = '0' * 64
    monkeypatch.setattr(BoundedToolRunner, 'run', lambda *args: pytest.fail('tampered projection reached backend'))
    with pytest.raises(ValueError, match='differs from regenerated'):
        api.validate_security_formula_logic_v2(report, source_bytes=raw, checkpoint=expanded_checkpoint, lake_executable='/missing/lake')
