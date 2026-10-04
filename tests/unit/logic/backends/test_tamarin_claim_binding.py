"""Tamarin summaries bind a complete requested lemma population, not attacks.

Rows and source fixtures are synthetic. No native Tamarin/Maude execution or
semantic attack reconstruction is claimed by these parser/consumer tests.
"""
from dataclasses import replace
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.protocol import tamarin as tm, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from tests.integration.logic_providers.test_protocol_execution_v2 import _protocol


MIB = 1024**2
DECLARATION = 'lemma secrecy:\n "All x #i. Secret(x) @ i ==> not (Ex #j. K(x) @ j)"\n'
SOURCE = 'theory Binding\nbegin\n'+DECLARATION+'end\n'
EXPECTED = {'claim:secret': 'secrecy'}
VERIFIED = 'lemma secrecy: verified (all-traces)\n'
FALSIFIED = 'lemma secrecy: falsified - found trace\n'


def forbidden(*args, **kwargs):
    pytest.fail('binding fixture reached native/shared execution or unvalidated trace reconstruction')


@pytest.fixture(autouse=True)
def no_native_pool_or_reconstructed_attack(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setattr(tm, 'parse_attack_trace', forbidden)
    monkeypatch.setattr(tm.NormalizedAttackTrace, 'replay', forbidden)


def parse(stdout=VERIFIED, *, stderr='', source=SOURCE, expected=None):
    return tm.parse_tamarin_claim_outcomes(stdout, stderr,
        claim_lemmas=EXPECTED if expected is None else expected, source=source)


def quarantine(outcomes, reason=None):
    status, result, accepted = tm.classify_claim_outcomes(outcomes)
    assert status is ResultStatus.UNKNOWN and not accepted and result is not None
    assert len(result.claim_ids) == len(set(result.claim_ids))
    if reason is not None:
        assert result.reason is reason
    assert all(item.attack_trace is None for item in outcomes)
    return result


@pytest.mark.parametrize('header', ['lemma secrecy:', 'lemma (modulo E) secrecy:',
    'lemma secrecy [sources]:', 'lemma secrecy [reuse,use_induction]:'])
def test_compiler_and_parser_accept_reviewed_headers_without_changing_source_identity(header):
    source = SOURCE.replace('lemma secrecy:', header)
    compiled = tm.TamarinCompiler().compile_source(source)
    before = compiled.to_dict()
    assert compiled.claim_lemmas.to_dict() == {'secrecy': 'secrecy'}
    outcomes = parse('secrecy (all-traces): verified (3 steps)\n',
        source=compiled.source, expected=compiled.claim_lemmas.to_dict())
    assert len(outcomes) == 1 and outcomes[0].claim_id == 'secrecy'
    assert outcomes[0].lemma_name == 'secrecy' and outcomes[0].verdict is tm.ClaimVerdict.VERIFIED
    assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)
    assert compiled.to_dict() == before and compiled.source == source
    assert compiled.source_digest == tm.content_digest(source)


@pytest.mark.parametrize('mask', [
    '// lemma ghost:\n',
    '/* lemma ghost:\n /* nested lemma second: */\n */\n',
    'text{*\nlemma ghost:\n*}\n',
    'restriction fixture:\n "lemma ghost:\n lemma another:"\n',
    "functions: 'lemma ghost:\n lemma another:'/0\n",
])
def test_comment_and_quoted_pseudodeclarations_do_not_create_claims(mask):
    source = SOURCE.replace('begin\n', 'begin\n'+mask)
    compiled = tm.TamarinCompiler().compile_source(source)
    assert compiled.claim_lemmas.to_dict() == {'secrecy': 'secrecy'}
    outcomes = parse(source=source, expected=compiled.claim_lemmas.to_dict())
    assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)
    assert compiled.source == source and compiled.source_digest == tm.content_digest(source)


@pytest.mark.parametrize('source', [
    SOURCE+'/* unterminated', SOURCE+'"unterminated', SOURCE+"'unterminated",
    SOURCE+'text{* unterminated', '#include "hidden.spthy"\n'+SOURCE,
    '#ifdef EXTRA\n'+SOURCE+'#endif\n',
    SOURCE.replace('lemma secrecy:', 'diffLemma secrecy:'),
    SOURCE.replace('lemma secrecy:', 'equivLemma secrecy:'),
    SOURCE.replace('lemma secrecy:', 'diffEquivLemma secrecy:'),
    SOURCE.replace('lemma secrecy:', 'lemma secrecy [heuristic={x}]:'),
    SOURCE.replace('lemma secrecy:', 'lemma secrecy [unknown_attribute]:'),
])
def test_unsupported_or_incomplete_source_shape_cannot_authorize_matching_output(source):
    outcomes = parse(source=source)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)
    assert tm.TamarinCompiler().compile_source(source).claim_lemmas.to_dict() == {}


@pytest.mark.parametrize('expected', [{}, {'claim:a': 'secrecy', 'claim:b': 'secrecy'},
    {'claim:secret': 'missing'}])
def test_empty_ambiguous_or_incomplete_expected_map_cannot_become_secure(expected):
    outcomes = parse(expected=expected)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


@pytest.mark.parametrize('expected', [{'claim:secret': ''}, {'claim:secret': 'a b'},
    {' claim:secret': 'secrecy'}, {'claim:secret': None}])
def test_malformed_map_records_raise_domain_error_before_result_binding(expected):
    with pytest.raises(tm.TamarinBackendError):
        parse(expected=expected, source=None)


def test_unknown_lemma_cannot_impersonate_an_expected_claim_id():
    expected = {'secrecy': 'actual'}
    source = SOURCE.replace('lemma secrecy:', 'lemma actual:')
    outcomes = parse(source=source, expected=expected)
    quarantine(outcomes)
    diagnostic = [item for item in outcomes if item.lemma_name == 'secrecy']
    missing = [item for item in outcomes if item.claim_id == 'secrecy']
    assert len(diagnostic) == len(missing) == 1
    assert diagnostic[0].claim_id not in expected and missing[0].lemma_name == 'actual'
    assert all(item.verdict is tm.ClaimVerdict.UNKNOWN for item in outcomes)


def test_diagnostic_identifiers_cannot_collide_with_reserved_looking_claim_ids():
    expected = {'unbound-result:0': 'secrecy'}
    outcomes = parse('lemma foreign: falsified - found trace\n', expected=expected)
    quarantine(outcomes)
    assert len({item.claim_id for item in outcomes}) == len(outcomes)
    assert any(item.claim_id == 'unbound-result:0' and item.lemma_name == 'secrecy' for item in outcomes)
    assert all(item.attack_trace is None for item in outcomes)


@pytest.mark.parametrize('variant', ['duplicate_source', 'missing_map', 'extra_map'])
def test_complete_source_population_must_match_compiled_map(variant):
    source, expected = SOURCE, EXPECTED
    if variant == 'duplicate_source':
        source = SOURCE.replace('end\n', DECLARATION+'end\n')
    elif variant == 'missing_map':
        source = SOURCE.replace('end\n', DECLARATION.replace('secrecy:', 'other:')+'end\n')
    else:
        expected = {**EXPECTED, 'claim:extra': 'other'}
    outcomes = parse(source=source, expected=expected)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


def test_missing_output_for_second_declared_lemma_quarantines_batch():
    source = SOURCE.replace('end\n', DECLARATION.replace('secrecy:', 'other:')+'end\n')
    outcomes = parse(source=source, expected={**EXPECTED, 'claim:other': 'other'})
    quarantine(outcomes)
    assert any(item.claim_id == 'claim:secret' and item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)
    assert any(item.claim_id == 'claim:other' and item.verdict is tm.ClaimVerdict.UNKNOWN for item in outcomes)


@pytest.mark.parametrize('output_name', ['Secrecy', 'SECRECY'])
def test_lemma_identifiers_are_case_sensitive(output_name):
    outcomes = parse(VERIFIED.replace('secrecy', output_name))
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


def test_same_bound_verdict_repeated_across_streams_is_deduplicated():
    outcomes = parse(VERIFIED+VERIFIED, stderr='secrecy (all-traces): verified (3 steps)\n')
    assert len(outcomes) == 1 and outcomes[0].claim_id == 'claim:secret'
    assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)


@pytest.mark.parametrize('other,verdict,reason', [
    (FALSIFIED, tm.ClaimVerdict.FALSIFIED, tm.QuarantineReason.DISAGREEMENT),
    ('lemma secrecy: analysis incomplete\n', tm.ClaimVerdict.INCOMPLETE, tm.QuarantineReason.INCONCLUSIVE),
    ('lemma secrecy: timeout\n', tm.ClaimVerdict.TIMEOUT, tm.QuarantineReason.INCONCLUSIVE),
])
@pytest.mark.parametrize('reverse', [False, True])
def test_conflicting_bound_outcomes_survive_stream_order_without_last_result_winning(other, verdict, reason, reverse):
    stdout, stderr = (other, VERIFIED) if reverse else (VERIFIED, other)
    outcomes = parse(stdout, stderr=stderr)
    assert {item.verdict for item in outcomes} == {tm.ClaimVerdict.VERIFIED, verdict}
    assert {item.claim_id for item in outcomes} == {'claim:secret'}
    result = quarantine(outcomes, reason)
    assert result.claim_ids == ('claim:secret',)


def test_unknown_extra_falsified_lemma_quarantines_valid_verified_result_without_trace():
    outcomes = parse(VERIFIED+'lemma foreign: falsified - found trace\nrule Reveal(secret)\n')
    quarantine(outcomes)
    assert any(item.claim_id == 'claim:secret' and item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)
    assert any(item.claim_id not in EXPECTED and item.verdict is tm.ClaimVerdict.UNKNOWN for item in outcomes)


@pytest.mark.parametrize('suffix', ['', 'rule Reveal(secret)\naction Send(secret)\n',
                                  'The attack was replayed successfully.\n'])
@pytest.mark.parametrize('source', [None, SOURCE])
def test_every_falsified_result_is_unvalidated_even_with_synthetic_trace_markers(source, suffix):
    outcomes = parse(FALSIFIED+suffix, source=source)
    assert len(outcomes) == 1 and outcomes[0].verdict is tm.ClaimVerdict.FALSIFIED
    assert 'validated' in outcomes[0].reason and outcomes[0].attack_trace is None
    quarantine(outcomes, tm.QuarantineReason.MALFORMED_OUTPUT)


@pytest.mark.parametrize('kind,verdict', [('all-traces', 'verified'), ('exists-trace', 'verified'),
    ('all-traces', 'falsified - found trace'), ('exists-trace', 'falsified - no trace found')])
def test_native_summary_rows_preserve_source_trace_kind_without_making_attacks(kind, verdict):
    source = SOURCE if kind == 'all-traces' else SOURCE.replace('lemma secrecy:\n', 'lemma secrecy:\n exists-trace\n')
    output = f'summary of summaries:\n\nanalyzed: input.spthy\nsecrecy ({kind}): {verdict} (3 steps)\n'
    outcomes = parse(output, source=source)
    assert len(outcomes) == 1 and outcomes[0].claim_id == 'claim:secret'
    assert outcomes[0].lemma_name == 'secrecy' and outcomes[0].attack_trace is None
    if verdict == 'verified':
        assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)
    else:
        assert outcomes[0].verdict is tm.ClaimVerdict.FALSIFIED
        quarantine(outcomes, tm.QuarantineReason.MALFORMED_OUTPUT)


@pytest.mark.parametrize('source_kind,output_kind', [('all-traces', 'exists-trace'), ('exists-trace', 'all-traces')])
def test_native_summary_trace_mode_must_match_source(source_kind, output_kind):
    source = SOURCE.replace('lemma secrecy:\n', f'lemma secrecy:\n {source_kind}\n')
    outcomes = parse(f'secrecy ({output_kind}): verified (3 steps)\n', source=source)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


@pytest.mark.parametrize('tail', ['lemma secrecy: verified rubbish\n',
    'secrecy (all-traces): verified (3 steps) trailing junk\n',
    'secrecy (all-traces): mystery (3 steps)\n'])
def test_malformed_known_summary_status_cannot_complete_a_claim(tail):
    outcomes = parse(tail)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


@pytest.mark.parametrize('malformed', ['secrecy (all-traces (bad)): falsified (2 steps)\n',
                                      'secrecy (all-traces) falsified (2 steps)\n'])
def test_malformed_known_duplicate_blocks_an_otherwise_verified_result(malformed):
    outcomes = parse('secrecy (all-traces): verified (3 steps)\n'+malformed)
    quarantine(outcomes)
    assert any(item.verdict is tm.ClaimVerdict.UNKNOWN for item in outcomes)


def test_source_echo_without_summary_cannot_enable_legacy_status_fallback():
    outcomes = parse(SOURCE+VERIFIED)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


@pytest.mark.parametrize('before_summary', [False, True])
def test_native_wellformedness_warning_prevents_verified_authority(before_summary):
    warning = 'WARNING: 1 wellformedness check failed!\nThe analysis results might be wrong!\n'
    output = ((warning if before_summary else '')+'summary of summaries:\n'
              +('' if before_summary else warning)+'secrecy (all-traces): verified (3 steps)\n')
    outcomes = parse(output)
    quarantine(outcomes)


@pytest.mark.parametrize('name', ['analyzed', 'output'])
def test_expected_lemma_name_cannot_hide_conflict_as_summary_metadata(name):
    source = SOURCE.replace('lemma secrecy:', f'lemma {name}:')
    outcomes = parse(f'summary of summaries:\n{name} (all-traces): verified (3 steps)\n{name}: falsified\n',
        source=source, expected={'claim:metadata': name})
    quarantine(outcomes)
    assert any(item.verdict is tm.ClaimVerdict.UNKNOWN for item in outcomes)


@pytest.mark.parametrize('separator', ['\x85', '\u2028'])
def test_unicode_display_separators_cannot_create_a_separate_verdict_line(separator):
    outcomes = parse('diagnostic prefix'+separator+VERIFIED)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


def test_native_crlf_and_closed_summary_metadata_remain_supported():
    output = ('summary of summaries:\r\n'+('='*78)+'\r\n'
              'analyzed: input.spthy\r\nprocessing time: 0.012s\r\n'
              'secrecy (all-traces): verified (3 steps)\r\n')
    outcomes = parse(output)
    assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)


def test_last_native_summary_overrides_earlier_echo_without_reusing_missing_rows():
    text = (VERIFIED+'summary of summaries:\nsecrecy (all-traces): verified (2 steps)\n'
            'summary of summaries:\nanalyzed: final.spthy\n')
    outcomes = parse(text)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


def test_output_echo_and_formula_pseudostatus_before_summary_are_ignored():
    text = ('lemma secrecy: falsified - found trace\nrule Fake(secret)\n'
            +SOURCE+'summary of summaries:\nsecrecy (all-traces): verified (4 steps)\n')
    outcomes = parse(text)
    assert len(outcomes) == 1 and outcomes[0].verdict is tm.ClaimVerdict.VERIFIED
    assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)


def test_each_stream_keeps_its_own_last_summary_and_conflicts_are_retained():
    stdout = 'summary of summaries:\nsecrecy (all-traces): verified (3 steps)\n'
    stderr = 'summary of summaries:\nsecrecy (all-traces): falsified - found trace (4 steps)\n'
    outcomes = parse(stdout, stderr=stderr)
    assert {item.verdict for item in outcomes} == {tm.ClaimVerdict.VERIFIED, tm.ClaimVerdict.FALSIFIED}
    quarantine(outcomes, tm.QuarantineReason.DISAGREEMENT)


def test_summary_in_one_stream_prevents_bare_other_stream_rows_from_filling_claim():
    outcomes = parse('summary of summaries:\nanalyzed: no-result.spthy\n', stderr=VERIFIED)
    quarantine(outcomes)
    assert not any(item.verdict is tm.ClaimVerdict.VERIFIED for item in outcomes)


def test_map_only_legacy_positive_parsing_remains_exact_and_explicit():
    outcomes = parse(VERIFIED, source=None)
    assert len(outcomes) == 1 and outcomes[0].claim_id == 'claim:secret'
    assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)


def test_actual_protocol_compiler_population_and_identity_survive_binding():
    document = _protocol()
    compiled = tm.TamarinCompiler().compile_protocol(document)
    before = compiled.to_dict()
    output = ''.join(f'lemma {name}: verified (all-traces)\n' for name in compiled.claim_lemmas.values())
    outcomes = parse(output, source=compiled.source, expected=compiled.claim_lemmas.to_dict())
    assert {item.claim_id for item in outcomes} == set(compiled.claim_lemmas)
    assert tm.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)
    assert compiled.to_dict() == before and compiled.protocol_document_id == document.document_id


def request():
    return BackendRequest(request_id='request:tamarin:binding', claim_id='claim:secret',
        declaration_id='declaration:protocol', claim_digest='1'*64,
        obligation_id='obligation:protocol', obligation_digest='2'*64,
        assumption_ids=('assumption:symbolic',), logic_family='cryptographic_protocol',
        query_kind=QueryKind.THEOREM_PROOF, requested_backend_id='tamarin',
        bounds=ExecutionBounds(timeout_ms=2000, max_memory_bytes=512*MIB, max_output_bytes=16384, max_steps=100),
        payload={'encoding': 'spthy', 'source': SOURCE})


@pytest.fixture
def native_fixture(tmp_path, monkeypatch):
    resources = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private-claim-binding-pool.json', proof_resource_sampler=lambda: resources,
        total_cpu_slots=4, total_memory_mb=1024, total_child_process_slots=16,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False))
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', lambda: owner)
    monkeypatch.setattr(process.shutil, 'which', lambda *args, **kwargs: sys.executable)
    calls, output, workspaces = [], [VERIFIED], []
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_lease_count'] == snapshot['active_root_lease_count'] == 1
        assert snapshot['allocated'] == {'cpu_slots': 2, 'memory_mb': 512}
        assert snapshot['allocated_child_process_slots'] == 8
        assert (invocation.cwd/'protocol.spthy').read_text() == SOURCE
        assert cancellation is not None and not cancellation.is_set()
        calls.append(invocation); workspaces.append(invocation.cwd)
        return process.RawProcessResult(returncode=0, stdout=output[0])
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, calls=calls, output=output)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not workspace.exists() for workspace in workspaces)


@pytest.mark.parametrize('stdout,status,reason', [
    (VERIFIED, ResultStatus.SECURE, None),
    (FALSIFIED+'rule Reveal(secret)\n', ResultStatus.UNKNOWN, 'malformed_output'),
    (VERIFIED+FALSIFIED, ResultStatus.UNKNOWN, 'disagreement'),
    (VERIFIED+'lemma foreign: verified (all-traces)\n', ResultStatus.UNKNOWN, 'inconclusive'),
])
@pytest.mark.parametrize('route', ['direct', 'registry', 'v2'])
def test_default_consumers_keep_complete_source_binding_and_never_replay_unvalidated_falsified_results(
        native_fixture, stdout, status, reason, route):
    native_fixture.output[0] = stdout
    req = request(); before = req.to_dict()
    if route == 'direct':
        outcome = tm.TamarinBackend().run(req)
        typed = outcome.result.to_dict()
        assert outcome.source_binding.request_digest == req.digest
        assert outcome.compile_result.source == SOURCE
    elif route == 'registry':
        attempt, result = registry.default_backend_registry().run(req, backend_id='tamarin')
        assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
        assert result.payload['result_status'] == status.value and not result.is_theorem_proof
        assert result.request_digest == attempt.request_digest == req.digest
        typed = result.payload['result'].to_dict()
    else:
        vreq = v2.ProtocolExecutionRequestV2(request_id='request:tamarin:v2:binding',
            provider='tamarin', source=SOURCE, bounds=req.bounds)
        vbefore = vreq.to_dict()
        result = v2.ProtocolExecutionEngineV2().execute(vreq)
        assert result.evidence.result_status is status and not result.is_theorem_authority
        assert result.protocol_established is (status is ResultStatus.SECURE)
        assert not result.evidence.attack.replayed and not result.evidence.attack.attack_traces
        assert vreq.to_dict() == vbefore
        typed = result.backend_result.to_dict()
    assert typed['status'] == status.value and typed['authority'] == ResultAuthority.PROTOCOL.value
    assert typed['translation_ceiling'] == (EvidenceAuthority.BOUNDED.value if status is ResultStatus.SECURE else EvidenceAuthority.NONE.value)
    receipt = typed['metadata']['protocol_receipt']
    assert receipt['accepted'] is (status is ResultStatus.SECURE)
    assert all(item['attack_trace'] is None for item in receipt['claim_outcomes'])
    assert (receipt['quarantine']['reason'] if receipt['quarantine'] else None) == reason
    assert receipt['compile_digest'] == tm.content_digest(SOURCE)
    assert typed['metadata']['source_binding']['source_digest'] == tm.content_digest(SOURCE)
    assert typed['metadata']['process']['stdout_digest'] == tm.content_digest(stdout)
    assert typed['bounds'] == req.bounds.to_dict()
    assert req.to_dict() == before and len(native_fixture.calls) == 1


def test_backend_passes_actual_compiled_source_instead_of_trusting_injected_map(native_fixture):
    class WrongMap(tm.TamarinCompiler):
        def compile_source(self, *args, **kwargs):
            return replace(super().compile_source(*args, **kwargs), claim_lemmas=FrozenMap({'secrecy': 'foreign'}))
    native_fixture.output[0] = 'lemma foreign: verified (all-traces)\n'
    outcome = tm.TamarinBackend(compiler=WrongMap()).run(request())
    assert outcome.result.status is ResultStatus.UNKNOWN and not outcome.receipt.accepted
    assert outcome.compile_result.source == SOURCE and outcome.compile_result.claim_lemmas['secrecy'] == 'foreign'
    assert all(item.verdict is tm.ClaimVerdict.UNKNOWN for item in outcome.receipt.claim_outcomes)
