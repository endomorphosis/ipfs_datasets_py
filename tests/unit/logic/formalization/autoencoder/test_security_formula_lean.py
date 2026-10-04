"""Real production inference, faithful pure models and actual Lean equations."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_lean as api
from .test_security_formula_decoder import formula_checkpoint


ARITHMETIC = b'def product(left, right):\n    temporary = (left - 7) * (right + 2)\n    return -temporary\n'
CONSTANT_STRING = b'def location(self):\n    return "https://example.invalid/repository"\n'


def project(checkpoint, source=ARITHMETIC, **kwargs):
    return api.project_security_formula_lean(source_bytes=source, checkpoint=checkpoint,
        source_path='example.py', **kwargs)


@pytest.mark.parametrize('source,result_sort', [(ARITHMETIC, 'Int'), (CONSTANT_STRING, 'String'),
    (b'def unicode(value):\n    return "\\u03bb"\n', 'String')])
def test_actual_weights_generate_source_equal_pure_equations(formula_checkpoint, source, result_sort):
    report = project(formula_checkpoint, source)
    assert report['status'] == 'candidate', report['frontiers']
    assert report['decode']['predicted_productions']
    assert report['decode']['validation']['source_AST_equivalent']
    assert report['candidate_model'] == report['source_model']
    assert report['candidate_model']['result_sort'] == result_sort
    assert report['learned_equation_count'] == 1
    assert report['model_equality_verified'] is True
    assert 'theorem predicted_matches_source_model' in report['lean_source']
    assert '\n  rfl\n' in report['lean_source']
    assert 'sorry' not in report['lean_source'] and 'axiom' not in report['lean_source']
    assert report['source_runtime_semantics_verified'] is report['security_specification_inferred'] is False


def test_constant_string_does_not_coerce_unused_self_parameter_to_integer(formula_checkpoint):
    report = project(formula_checkpoint, CONSTANT_STRING)
    assert report['decode']['status'] == 'candidate'
    assert report['decode']['native_artifact'] is None
    assert report['candidate_model']['parameters'] == [{'source_name':'self', 'name':'p0', 'sort':'opaque'}]
    assert 'def predicted {T0 : Type} (p0 : T0) : String' in report['lean_source']


@pytest.mark.parametrize('options', [{'model_enabled': False}, {'weight_ablation': 'zero_production_heads'}])
def test_equations_require_actual_correct_learned_productions(formula_checkpoint, options):
    report = project(formula_checkpoint, **options)
    assert report['status'] == 'unsupported'
    assert report['learned_equation_count'] == 0
    assert report['lean_source'] is report['candidate_model'] is None
    assert report['frontiers'] == ['no_independently_checked_learned_candidate']
    receipt = api.validate_security_formula_lean(report, source_bytes=ARITHMETIC,
        checkpoint=formula_checkpoint, lake_executable='/missing/lake')
    assert receipt['status'] == 'not_run' and not receipt['backend_executed']


@pytest.mark.parametrize('source', [
    b'@unreviewed_effect()\ndef f(value):\n    return value + 1\n',
    b'def f(value):\n    return str(value)\n',
    b'def f(value):\n    return "a" + "b"\n',
    b'def f(value):\n    return value == 1\n',
    b'def f(value):\n    value = value + 1\n    return value\n',
    b'def f(value):\n    return value / 2\n',
    b'def f(value):\n    return 1.5\n',
])
def test_unmodeled_effects_types_or_operators_never_become_equations(formula_checkpoint, source):
    report = project(formula_checkpoint, source)
    assert report['status'] == 'unsupported'
    assert report['lean_source'] is None and report['learned_equation_count'] == 0
    assert report['frontiers']


@pytest.mark.parametrize('change', ['lean', 'source_model', 'candidate_source', 'source_hash', 'projection_hash'])
def test_tampering_refused_before_any_lake_execution(formula_checkpoint, monkeypatch, change):
    from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
    report = deepcopy(project(formula_checkpoint))
    if change == 'lean': report['lean_source'] += '\naxiom unsound : False\n'
    elif change == 'source_model': report['source_model']['result_sort'] = 'String'
    elif change == 'candidate_source': report['decode']['candidate_source'] = 'def f(x): return 0'
    elif change == 'source_hash': report['source_sha256'] = '0' * 64
    else: report['projection_sha256'] = '0' * 64
    monkeypatch.setattr(BoundedToolRunner, 'run', lambda *args: pytest.fail('tampered Lean was executed'))
    with pytest.raises(ValueError, match='differs from regenerated'):
        api.validate_security_formula_lean(report, source_bytes=ARITHMETIC,
            checkpoint=formula_checkpoint, lake_executable='/missing/lake')


def test_changed_source_refused_before_lake_execution(formula_checkpoint):
    report = project(formula_checkpoint)
    with pytest.raises(ValueError, match='differs from regenerated'):
        api.validate_security_formula_lean(report, source_bytes=ARITHMETIC.replace(b'7',b'8'),
            checkpoint=formula_checkpoint, lake_executable='/missing/lake')


@pytest.mark.parametrize('source', [ARITHMETIC, CONSTANT_STRING, b'def unicode(value):\n    return "\\u03bb"\n'])
def test_installed_native_lake_builds_actual_model_equality(formula_checkpoint, source):
    executables = sorted((Path.home()/'.elan'/'toolchains').glob('*/bin/lake'))
    if not executables:
        pytest.skip('native installed Lake toolchain unavailable')
    report = project(formula_checkpoint, source)
    receipt = api.validate_security_formula_lean(report, source_bytes=source,
        checkpoint=formula_checkpoint, lake_executable=str(executables[-1]))
    assert receipt['status'] == 'passed', receipt
    assert receipt['backend_executed'] and receipt['model_equality_proved']
    assert receipt['command'][1:] == ['build', 'SecurityEquations']
    assert receipt['source_runtime_semantics_verified'] is False
