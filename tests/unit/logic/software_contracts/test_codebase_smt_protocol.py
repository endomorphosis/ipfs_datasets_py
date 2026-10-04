"""Pure single-check protocol tests; no native tools or resource owner needed."""
import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_smt_protocol as protocol


BASE = '(set-logic QF_LIA)\n(assert (= 1 1))\n(check-sat)\n'


@pytest.mark.parametrize("suffix,model,core", [
    ("", False, False), ("(get-model)\n", True, False),
    ("(get-unsat-core)\n", False, True),
    ("(get-model)\n(get-unsat-core)\n", True, True),
    ("(get-unsat-core)\n(get-model)\n", True, True),
])
def test_split_preserves_only_exact_prefix(suffix, model, core):
    assert protocol.split_smt_script(BASE + suffix) == (BASE, model, core)


def test_split_uses_lexical_commands_not_text_in_strings_comments_or_identifiers():
    prefix = ('; (check-sat) (get-model)\n'
              '(set-info :source "λ (check-sat) ""(get-unsat-core)""")\n'
              '(declare-fun |(check-sat)| () Int)\n'
              '(assert (= |(check-sat)| 2))\n(check-sat)')
    source = prefix + '; trailing (get-model)\n(get-model) ; (get-model)\n'
    assert protocol.split_smt_script(source) == (prefix + '\n', True, False)


def test_actual_compiler_constant_fixture_splits_without_rewriting_obligation():
    from ipfs_datasets_py.logic.backends.smt.compiler import (
        INT_SORT, SmtFunDecl, SmtObligation, SmtQueryMode,
        SoftwareVerificationSMTCompiler, term_eq, term_int, term_symbol,
    )
    obligation = SmtObligation(
        obligation_id='obl:protocol-constant',
        query_mode=SmtQueryMode.SATISFIABILITY,
        features=('arithmetic', 'equality'),
        goal=term_eq(term_symbol('n'), term_int(7)),
        functions=(SmtFunDecl('n', range=INT_SORT, is_const=True),),
        request_model=True, request_unsat_core=True,
    )
    compiled = SoftwareVerificationSMTCompiler().compile(obligation)
    assert '(declare-const n Int)' in compiled.smtlib
    base, model, core = protocol.split_smt_script(compiled.smtlib)
    assert model is core is True
    assert base + '(get-model)\n(get-unsat-core)\n' == compiled.smtlib
    assert protocol.artifact_script(base, 'sat', model, core) == base + '(get-model)\n'
    assert protocol.artifact_script(base, 'unsat', model, core) == base + '(get-unsat-core)\n'


@pytest.mark.parametrize("source", [
    '(get-model)\n(check-sat)', '(check-sat)(check-sat)',
    '(check-sat)(assert true)', '(check-sat)(exit)', '(push 1)(check-sat)',
    '(check-sat-assuming ())(check-sat)', '(check-sat)(get-info :all-statistics)',
    '(check-sat)(get-model)(get-model)', '(check-sat)(get-unsat-core)(get-unsat-core)',
    '(check-sat true)', '(check-sat)(get-model x)', '(check-sat)(get-unsat-core x)',
    '(assert true)', 'sat', '(|check-sat|)', '("check-sat")',
    '(echo "sat")(check-sat)', '(set-option :regular-output-channel "x")(check-sat)',
    '(set-option :produce-models false)(check-sat)', '(assert)(check-sat)',
    '(check-sat)(', '(check-sat)garbage',
])
def test_split_rejects_incremental_malformed_or_trailing_commands(source):
    with pytest.raises(protocol.SmtProtocolError):
        protocol.split_smt_script(source)


@pytest.mark.parametrize("verdict", ['sat', 'unsat', 'unknown'])
def test_clean_verdict_allows_only_success_acknowledgments_and_comments(verdict):
    assert protocol.parse_verdict(f'; sat unsat\nsuccess\n{verdict} ; unknown\nsuccess\n') == verdict


@pytest.mark.parametrize("stdout", [
    'sat\nunsat', 'sat\nsat', 'unsat\nunknown', 'success', '; sat',
    'SAT', '"sat"', '|sat|', '(sat)', 'sat\n()', 'sat\nwarning',
    '(error "ignored?")\nunsat', 'unsat\n(error "model is not available")',
    'sat\n(:reason-unknown "x")',
])
def test_verdict_rejects_artifacts_errors_noise_and_multiple_answers(stdout):
    with pytest.raises(protocol.SmtProtocolError):
        protocol.parse_verdict(stdout)


@pytest.mark.parametrize("verdict,model,core,command", [
    ('sat', True, True, 'get-model'), ('unsat', True, True, 'get-unsat-core'),
    ('sat', False, True, None), ('unsat', True, False, None),
    ('unknown', True, True, None), ('sat', False, False, None),
])
def test_artifact_script_requests_only_applicable_artifact(verdict, model, core, command):
    expected = None if command is None else BASE + f'({command})\n'
    assert protocol.artifact_script(BASE, verdict, model, core) == expected


@pytest.mark.parametrize("args", [
    (BASE + '(get-model)', 'sat', True, False), (BASE, 'SAT', True, False),
    (BASE, 'sat', 1, False), (BASE, 'unsat', False, None),
])
def test_artifact_script_validates_base_verdict_and_flags(args):
    with pytest.raises(protocol.SmtProtocolError):
        protocol.artifact_script(*args)


# Shapes retained from both native outputs in the October 2 query benchmark's
# CAS. The old incompatible second artifact diagnostic is tested separately.
@pytest.mark.parametrize("stdout", [
    'sat\n(\n  (define-fun n () Int\n    0)\n)\n',
    'sat\n(\n(define-fun n () Int (- 7))\n(define-fun result () Int 0)\n)\n',
    'sat\n(model (define-fun f ((x Int)) Int (+ x 1)))',
    'sat\n()', 'sat\n(model)',
    'success\nsat\n((define-fun |odd (name)| () String "(error ""data"") ;"))\nsuccess',
])
def test_accepts_z3_cvc5_model_shapes_and_empty_models(stdout):
    assert protocol.validate_artifact_response(stdout, 'sat', 'model') is None


@pytest.mark.parametrize("stdout", [
    'unsat\n()', 'unsat\n(\n)\n', 'unsat\n(assume_0 body_return_0)',
    '; sat\nsuccess\nunsat\n(|assert with spaces| |(error data)|)\n',
])
def test_accepts_core_symbols_and_empty_cores(stdout):
    assert protocol.validate_artifact_response(stdout, 'unsat', 'unsat_core') is None


@pytest.mark.parametrize("stdout,verdict,kind", [
    ('unsat\n(error "line 14 column 10: model is not available")\n()\n', 'unsat', 'unsat_core'),
    ('unsat\n(error "cannot get model unless after a SAT or UNKNOWN response.")\n(\n)\n', 'unsat', 'unsat_core'),
    ('sat\n((define-fun n () Int 0))\n(error "line 15 column 15: unsat core is not available")\n', 'sat', 'model'),
    ('sat\n((define-fun n () Int 0))\n(error "cannot get unsat core unless in unsat mode.")\n', 'sat', 'model'),
    ('unsat\n()', 'sat', 'model'), ('sat\n()', 'unsat', 'unsat_core'),
    ('unknown\n()', 'sat', 'model'), ('sat', 'sat', 'model'),
    ('unsat', 'unsat', 'unsat_core'), ('sat\nsat\n()', 'sat', 'model'),
    ('sat\n()\n()', 'sat', 'model'), ('unsat\n()\nunknown', 'unsat', 'unsat_core'),
    ('sat\n(arbitrary)', 'sat', 'model'), ('sat\n((define-fun n () Int))', 'sat', 'model'),
    ('sat\n((define-fun n () Int 0 extra))', 'sat', 'model'),
    ('sat\n((define-fun n (x) Int 0))', 'sat', 'model'),
    ('sat\n((define-fun n ((x)) Int 0))', 'sat', 'model'),
    ('sat\n((define-fun n () Int (error "nested"))))', 'sat', 'model'),
    ('unsat\n((assume_0))', 'unsat', 'unsat_core'),
    ('unsat\n("not an assertion")', 'unsat', 'unsat_core'),
    ('unsat\n(42)', 'unsat', 'unsat_core'), ('unsat\n(:reason)', 'unsat', 'unsat_core'),
    ('sat\n(', 'sat', 'model'), ('unsat\n()', 'unknown', 'unsat_core'),
    ('sat\n()', 'sat', 'core'), ('sat\n()', [], 'model'),
])
def test_artifacts_fail_closed_for_errors_mismatch_noise_or_malformed_shape(stdout, verdict, kind):
    with pytest.raises(protocol.SmtProtocolError):
        protocol.validate_artifact_response(stdout, verdict, kind)


class TextSubclass(str):
    def encode(self, *args, **kwargs):
        raise AssertionError('invalid subclass must not reach encoding')


@pytest.mark.parametrize("text", [None, b'sat', TextSubclass('sat'), '', '\x00sat', '\ud800',
    'x' * (protocol.MAX_PROTOCOL_BYTES + 1), 'λ' * (protocol.MAX_PROTOCOL_BYTES // 2 + 1)],
    ids=['none', 'bytes', 'subclass', 'empty', 'nul', 'surrogate', 'characters', 'utf8-bytes'])
def test_exact_text_and_byte_fences(text):
    with pytest.raises(protocol.SmtProtocolError):
        protocol.parse_verdict(text)


def test_depth_and_token_limits_fail_closed_without_recursive_overflow():
    with pytest.raises(protocol.SmtProtocolError):
        protocol.validate_artifact_response('sat\n' + '(' * 70 + ')' * 70, 'sat', 'model')
    with pytest.raises(protocol.SmtProtocolError):
        protocol.parse_verdict('success ' * protocol.MAX_PROTOCOL_TOKENS + 'sat')


def test_legacy_quoted_symbol_backslash_extension_is_rejected():
    with pytest.raises(protocol.SmtProtocolError):
        protocol.validate_artifact_response('unsat\n(|legacy\\|symbol|)', 'unsat', 'unsat_core')


def test_exact_byte_cap_and_artifact_suffix_budget():
    padding = ';' + 'x' * (protocol.MAX_PROTOCOL_BYTES - len(BASE) - 2) + '\n'
    source = padding + BASE
    assert len(source.encode()) == protocol.MAX_PROTOCOL_BYTES
    assert protocol.split_smt_script(source) == (source, False, False)
    with pytest.raises(protocol.SmtProtocolError):
        protocol.artifact_script(source, 'sat', True, False)
