"""Source-qualified native secrecy results preserve claim identity and limits.

All execution uses private scheduler state and a synthetic executor. Native
stdout fixtures below are copied from the retained admission qualification;
they do not claim that these tests execute ProVerif or replay its attacks.
"""
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission as admission
from ipfs_datasets_py.logic.backends.protocol import proverif as pv, execution_v2 as v2
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
PREFIX = 'free c: channel.\nfree s: bitstring [private].\nquery attacker(s).\n'
PRIVATE = PREFIX+'process 0'
DISCLOSED = PREFIX+'process out(c,s)'
EXPECTED = {'query:0': 'attacker(s)'}

# Provenance: workspace/proverif-default-admission-qualification-20261004/
# native-final/result.json, SHA256
# 531d946470ee0b81013d7d4db14de98951df47de6fe5b01b9a41bc18920ba291.
# Pointers: /cases/{0,1}/native/lifecycle/result/stdout, respectively.
NATIVE_TRUE = (
    'Process 0 (that is, the initial process):\n0\n\n'
    '-- Query not attacker(s[]) in process 0.\n'
    'Translating the process into Horn clauses...\nCompleting...\n'
    'Starting query not attacker(s[])\nRESULT not attacker(s[]) is true.\n\n'
    '--------------------------------------------------------------\nVerification summary:\n\n'
    'Query not attacker(s[]) is true.\n\n'
    '--------------------------------------------------------------\n\n')
NATIVE_FALSE = (
    'Process 0 (that is, the initial process):\n{1}out(c, s)\n\n'
    '-- Query not attacker(s[]) in process 0.\n'
    'Translating the process into Horn clauses...\nCompleting...\n'
    'Starting query not attacker(s[])\ngoal reachable: attacker(s[])\n\nDerivation:\n\n'
    '1. The message s[] may be sent to the attacker at output {1}.\nattacker(s[]).\n\n'
    '2. By 1, attacker(s[]).\nThe goal is reached, represented in the following fact:\n'
    'attacker(s[]).\n\n\nA more detailed output of the traces is available with\n'
    '  set traceDisplay = long.\n\nout(c, ~M) with ~M = s at {1}\n\n'
    'The attacker has the message ~M = s.\nA trace has been found.\n'
    'RESULT not attacker(s[]) is false.\n\n'
    '--------------------------------------------------------------\nVerification summary:\n\n'
    'Query not attacker(s[]) is false.\n\n'
    '--------------------------------------------------------------\n\n')


def forbidden(*args, **kwargs):
    pytest.fail('query-binding fixture reached native/shared execution or fabricated a trace')


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', forbidden)
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', forbidden)


def parse(stdout, *, source=PRIVATE, expected=None, stderr=''):
    return pv.parse_proverif_claim_outcomes(stdout, stderr,
        claim_queries=EXPECTED if expected is None else expected, source=source)


def assert_unaccepted(outcomes):
    status, quarantine, accepted = pv.classify_claim_outcomes(outcomes)
    assert status is ResultStatus.UNKNOWN and not accepted and quarantine is not None
    return quarantine


@pytest.mark.parametrize('source,stdout,verdict,status', [
    (PRIVATE, NATIVE_TRUE, pv.ClaimVerdict.TRUE, ResultStatus.SECURE),
    (DISCLOSED, NATIVE_FALSE, pv.ClaimVerdict.FALSE, ResultStatus.UNKNOWN),
])
def test_retained_native_stdout_maps_only_to_its_declared_claim(source, stdout, verdict, status, monkeypatch):
    monkeypatch.setattr(pv, 'parse_attack_trace', forbidden)
    compiled = pv.ProVerifCompiler().compile_source(source)
    before = compiled.to_dict()
    outcomes = parse(stdout, source=compiled.source, expected=compiled.claim_queries.to_dict())
    assert len(outcomes) == 1
    item = outcomes[0]
    assert item.claim_id == 'query:0' and item.verdict is verdict
    assert item.query_text == 'not attacker(s[])' and item.attack_trace is None
    classified, quarantine, accepted = pv.classify_claim_outcomes(outcomes)
    assert classified is status and accepted is (status is ResultStatus.SECURE)
    if verdict is pv.ClaimVerdict.FALSE:
        assert item.reason and quarantine is not None
    assert compiled.to_dict() == before and compiled.source == source
    assert compiled.claim_queries.to_dict() == EXPECTED
    assert compiled.source_digest == pv.content_digest(source)


@pytest.mark.parametrize('source,expected,query', [
    ('free s: bitstring.\nquery attacker(s).\nprocess 0', EXPECTED, 'not attacker(s[])'),
    ('free Secret: bitstring [private].\nquery attacker(Secret).\nprocess 0',
     {'claim:secret': 'attacker(Secret)'}, 'not attacker(Secret[])'),
    (' free s : bitstring [ private ] .\nquery attacker ( s ) .\nprocess 0',
     {'claim:spaces': 'attacker ( s )'}, 'not attacker ( s [ ] )'),
    ('(* process; query attacker(fake). (* nested comment *) *)\n'+PRIVATE,
     EXPECTED, 'not attacker(s[])'),
])
def test_reviewed_free_name_and_whitespace_forms_bind_without_changing_native_query(source, expected, query):
    outcomes = parse(f'RESULT {query} is true.\n', source=source, expected=expected)
    assert len(outcomes) == 1 and outcomes[0].claim_id == next(iter(expected))
    assert outcomes[0].query_text == query
    assert pv.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)


UNQUALIFIED = [None, '', 'query attacker(s).\nprocess 0',
    'query attacker(s).\nprocess new s: bitstring; 0',
    'fun s(): bitstring.\nquery attacker(s).\nprocess 0',
    'free S: bitstring [private].\nquery attacker(s).\nprocess 0',
    'free s: bitstring.\nfree s: bitstring.\nquery attacker(s).\nprocess 0',
    'type custom.\n'+PRIVATE,
    'set traceDisplay = "long".\n'+PRIVATE,
    PREFIX+'(* unfinished process comment',
    PREFIX,
    '(* free s: bitstring. *)\nquery attacker(s).\nprocess 0',
]


@pytest.mark.parametrize('source', UNQUALIFIED)
def test_alias_is_not_guessed_without_complete_reviewed_source_context(source):
    outcomes = parse('RESULT not attacker(s[]) is true.\n', source=source)
    assert_unaccepted(outcomes)
    assert not any(item.verdict is pv.ClaimVerdict.TRUE for item in outcomes)
    assert all(item.attack_trace is None for item in outcomes)


def test_non_native_leading_underscore_identifier_does_not_qualify_alias():
    source = 'free _s: bitstring [private].\nquery attacker(_s).\nprocess 0'
    outcomes = parse('RESULT not attacker(_s[]) is true.\n', source=source,
                     expected={'claim:identifier': 'attacker(_s)'})
    assert_unaccepted(outcomes)
    assert not any(item.verdict is pv.ClaimVerdict.TRUE for item in outcomes)


@pytest.mark.parametrize('query', ['attacker(s)', 'attacker(s[])', 'not attacker(S[])',
    'not attacker(s[x])', 'not attacker(s[!1])', 'not attacker(s[][])',
    'not attacker(f(s[]))', 'not not attacker(s[])', 'not attacker(s[]) phase 1',
    'not attacker(s)'])
def test_ground_claim_does_not_use_wrong_polarity_or_general_term_rewriting(query):
    outcomes = parse(f'RESULT {query} is true.\n')
    assert_unaccepted(outcomes)
    assert not any(item.verdict is pv.ClaimVerdict.TRUE for item in outcomes)


@pytest.mark.parametrize('token', ['cannot be proved', 'is cannot be proved'])
def test_native_and_legacy_inconclusive_spelling_preserves_bound_claim(token):
    outcomes = parse(f'RESULT not attacker(s[]) {token}.\n')
    assert len(outcomes) == 1 and outcomes[0].claim_id == 'query:0'
    assert outcomes[0].verdict is pv.ClaimVerdict.CANNOT_PROVE
    assert outcomes[0].query_text == 'not attacker(s[])'
    assert_unaccepted(outcomes)


@pytest.mark.parametrize('expected', [{}, {'claim:a': 'not attacker(s)', 'claim:b': 'not  attacker(s)'}])
def test_empty_or_ambiguous_expected_map_cannot_mint_a_claim(expected):
    outcomes = parse('RESULT not attacker(s) is true.\n', source=None, expected=expected)
    assert_unaccepted(outcomes)
    assert all(item.verdict is pv.ClaimVerdict.UNKNOWN for item in outcomes)
    assert all(item.attack_trace is None for item in outcomes)


def test_extra_unbound_result_quarantines_an_otherwise_valid_true_claim(monkeypatch):
    monkeypatch.setattr(pv, 'parse_attack_trace', forbidden)
    outcomes = parse(NATIVE_TRUE+'RESULT not attacker(unrelated[]) is false.\n-> out(c, unrelated)\n')
    assert_unaccepted(outcomes)
    assert [(item.claim_id, item.verdict) for item in outcomes if item.verdict is pv.ClaimVerdict.TRUE] == [
        ('query:0', pv.ClaimVerdict.TRUE)]
    assert any(item.verdict is pv.ClaimVerdict.UNKNOWN and item.reason for item in outcomes)
    assert all(item.attack_trace is None for item in outcomes)


def test_identical_repeated_native_result_is_deduplicated():
    outcomes = parse(NATIVE_TRUE, stderr='RESULT not attacker(s[]) is true.\n')
    assert len(outcomes) == 1 and outcomes[0].claim_id == 'query:0'
    assert pv.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)


def test_conflicting_result_for_one_claim_is_quarantined_without_duplicate_id_exception():
    outcomes = parse(NATIVE_TRUE, stderr='RESULT not attacker(s[]) is false.\n')
    assert {item.verdict for item in outcomes} == {pv.ClaimVerdict.TRUE, pv.ClaimVerdict.FALSE}
    assert {item.claim_id for item in outcomes} == {'query:0'}
    quarantine = assert_unaccepted(outcomes)
    assert quarantine.reason is pv.QuarantineReason.DISAGREEMENT
    assert quarantine.claim_ids == ('query:0',)


@pytest.mark.parametrize('expected', [
    {'claim:missing': 'attacker(other)'},
    {'claim:a': 'attacker(s)', 'claim:b': 'attacker(s)'},
])
def test_compiled_query_multiset_must_match_every_actual_source_query(expected):
    outcomes = parse(NATIVE_TRUE, expected=expected)
    assert_unaccepted(outcomes)
    assert set(expected).issubset({item.claim_id for item in outcomes})
    assert not any(item.verdict is pv.ClaimVerdict.TRUE for item in outcomes)


def test_missing_second_ground_query_prevents_batch_acceptance():
    source = ('free s: bitstring [private].\nfree t: bitstring [private].\n'
              'query attacker(s).\nquery attacker(t).\nprocess 0')
    expected = {'claim:s': 'attacker(s)', 'claim:t': 'attacker(t)'}
    outcomes = parse(NATIVE_TRUE, source=source, expected=expected)
    assert_unaccepted(outcomes)
    assert any(item.claim_id == 'claim:s' and item.verdict is pv.ClaimVerdict.TRUE for item in outcomes)
    assert any(item.claim_id == 'claim:t' and item.verdict is pv.ClaimVerdict.UNKNOWN for item in outcomes)


@pytest.mark.parametrize('source', [
    'free s: bitstring.\nfree t: bitstring.\n(* claim:one *)\nquery attacker(s).\nquery attacker(t).\nprocess 0',
    'free s: bitstring.\nfree t: bitstring.\n(* claim:one *)\nquery attacker(s).\n(* claim:one *)\nquery attacker(t).\nprocess 0',
    'free s: bitstring.\nquery attacker(s).\nquery attacker(s).\nprocess 0',
])
def test_legacy_compiler_dropped_or_duplicate_queries_cannot_enable_new_alias(source):
    compiled = pv.ProVerifCompiler().compile_source(source)
    outcomes = parse(NATIVE_TRUE, source=compiled.source, expected=compiled.claim_queries.to_dict())
    assert_unaccepted(outcomes)
    assert not any(item.verdict is pv.ClaimVerdict.TRUE for item in outcomes)
    assert compiled.source == source


@pytest.mark.parametrize('query', ['not attacker(s)',
    'inj-event(Accept(x)) ==> inj-event(Begin(x))', 'event(Done(x))'])
def test_explicit_legacy_exact_query_matching_remains_available(query):
    outcomes = parse(f'RESULT {query} is true.\n', source=None, expected={'claim:legacy': query})
    assert len(outcomes) == 1 and outcomes[0].claim_id == 'claim:legacy'
    assert pv.classify_claim_outcomes(outcomes) == (ResultStatus.SECURE, None, True)


def test_legacy_exact_binding_preserves_identifier_case():
    outcomes = parse('RESULT event(done(x)) is true.\n', source=None,
                     expected={'claim:case': 'event(Done(x))'})
    assert_unaccepted(outcomes)
    assert not any(item.verdict is pv.ClaimVerdict.TRUE for item in outcomes)


@pytest.mark.parametrize('trace', ['', '-> event Accept(s)\n-> out(c,s)\n', NATIVE_FALSE])
def test_new_native_false_binding_never_fabricates_or_borrows_replay(trace, monkeypatch):
    monkeypatch.setattr(pv, 'parse_attack_trace', forbidden)
    monkeypatch.setattr(pv.NormalizedAttackTrace, 'replay', forbidden)
    outcomes = parse('RESULT not attacker(s[]) is false.\n'+trace, source=DISCLOSED)
    assert len(outcomes) == 1 and outcomes[0].verdict is pv.ClaimVerdict.FALSE
    assert outcomes[0].attack_trace is None and outcomes[0].reason
    assert_unaccepted(outcomes)


def test_legacy_synthetic_arrow_trace_compatibility_remains_explicit():
    text = 'RESULT not attacker(s) is false.\n-> event Accept(s)\n-> out(c,s)\n'
    outcomes = parse(text, source=None, expected={'claim:legacy': 'not attacker(s)'})
    assert outcomes[0].attack_trace is not None
    assert outcomes[0].attack_trace.replay()  # Existing structural tokens, not semantic replay.
    assert pv.classify_claim_outcomes(outcomes)[0] is ResultStatus.ATTACK_FOUND


def request(source):
    return BackendRequest(request_id='request:proverif:native-binding', claim_id='claim:secrecy',
        declaration_id='declaration:protocol', claim_digest='1'*64,
        obligation_id='obligation:protocol', obligation_digest='2'*64,
        assumption_ids=('assumption:symbolic',), logic_family='cryptographic_protocol',
        query_kind=QueryKind.THEOREM_PROOF, requested_backend_id='proverif',
        bounds=ExecutionBounds(timeout_ms=2000, max_memory_bytes=64*MIB,
                               max_output_bytes=8192, max_steps=100),
        payload={'encoding': 'pv', 'source': source})


@pytest.fixture
def native_fixture(tmp_path, monkeypatch):
    resources = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private-query-pool.json', proof_resource_sampler=lambda: resources,
        total_cpu_slots=2, total_memory_mb=256, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False))
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', lambda: owner)
    monkeypatch.setattr(process.shutil, 'which', lambda *a, **k: sys.executable)
    calls, workspaces = [], []
    def execute(self, invocation, cancellation=None):
        snapshot = owner.snapshot()
        assert snapshot['active_lease_count'] == snapshot['active_root_lease_count'] == 1
        assert snapshot['allocated'] == {'cpu_slots': 1, 'memory_mb': 64}
        assert snapshot['allocated_child_process_slots'] == 1
        assert cancellation is not None and not cancellation.is_set()
        source = (invocation.cwd/'protocol.pv').read_text()
        assert source in {PRIVATE, DISCLOSED}
        calls.append(source); workspaces.append(invocation.cwd)
        return process.RawProcessResult(returncode=0, stdout=NATIVE_TRUE if source == PRIVATE else NATIVE_FALSE)
    monkeypatch.setattr(process.SubprocessExecutor, 'execute', execute)
    yield SimpleNamespace(owner=owner, calls=calls)
    snapshot = owner.snapshot()
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
    assert all(not workspace.exists() for workspace in workspaces)


@pytest.mark.parametrize('source,stdout,status', [(PRIVATE, NATIVE_TRUE, ResultStatus.SECURE),
                                                (DISCLOSED, NATIVE_FALSE, ResultStatus.UNKNOWN)])
@pytest.mark.parametrize('route', ['direct', 'registry', 'v2'])
def test_native_binding_propagates_without_changing_source_or_overstating_authority(
        native_fixture, source, stdout, status, route):
    req = request(source)
    before = req.to_dict()
    if route == 'direct':
        outcome = pv.ProVerifBackend().run(req)
        typed = outcome.result.to_dict()
        assert outcome.source_binding.request_digest == req.digest
    elif route == 'registry':
        attempt, result = registry.default_backend_registry().run(req, backend_id='proverif')
        assert attempt.status.value == 'succeeded' and result.status.value == 'unknown'
        assert not result.is_theorem_proof and result.payload['result_status'] == status.value
        assert result.request_digest == attempt.request_digest == req.digest
        assert result.attempt_digest == attempt.digest
        typed = result.payload['result'].to_dict()
    else:
        vreq = v2.ProtocolExecutionRequestV2(request_id='request:proverif:v2:binding',
            provider='proverif', source=source, source_format='pv', bounds=req.bounds)
        vbefore = vreq.to_dict()
        result = v2.ProtocolExecutionEngineV2().execute(vreq)
        assert result.evidence.result_status is status and not result.evidence.is_theorem_authority
        assert result.evidence.protocol_established is (status is ResultStatus.SECURE)
        assert not result.evidence.attack.replayed and not result.evidence.attack.attack_traces
        assert vreq.to_dict() == vbefore
        typed = result.backend_result.to_dict()
    assert typed['status'] == status.value and typed['authority'] == ResultAuthority.PROTOCOL.value
    assert typed['translation_ceiling'] == (EvidenceAuthority.BOUNDED.value if status is ResultStatus.SECURE else EvidenceAuthority.NONE.value)
    receipt = typed['metadata']['protocol_receipt']
    assert receipt['accepted'] is (status is ResultStatus.SECURE)
    assert len(receipt['claim_outcomes']) == 1
    claim = receipt['claim_outcomes'][0]
    assert claim['claim_id'] == 'query:0' and claim['query_text'] == 'not attacker(s[])'
    assert claim['verdict'] == ('true' if status is ResultStatus.SECURE else 'false')
    assert claim['attack_trace'] is None
    assert typed['metadata']['source_binding']['source_digest'] == pv.content_digest(source)
    assert receipt['compile_digest'] == pv.content_digest(source)
    assert typed['metadata']['process']['stdout_digest'] == pv.content_digest(stdout)
    assert typed['metadata']['process']['returncode'] == 0
    assert typed['metadata']['process']['workspace_cleaned']
    assert req.to_dict() == before and native_fixture.calls == [source]
