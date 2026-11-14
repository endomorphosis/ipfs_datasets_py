"""Planned request integrity from explicitly synthetic retained engineering data.

No native execution, observed usage, theorem result or receipt is established.
The real public source, packet and kernel projection owners run unmocked.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_kernel_requests_v2 as owner
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_kernel_claims_v2 as projection_owner
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_elaboration_packet_v2 as reader
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_elaboration_native_v2 as native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_index_v2 as index_owner
from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.ir_core import protocols
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope='module')
def inputs():
    fixture = importlib.import_module('tests.unit.logic.autoformal.test_legal_corpus_definition_use_preservation_kernel_claims_v2')
    old, lineage, files, arguments = fixture.synthetic_kernel_inputs('fol')
    positional = (files, lineage, old.files, old.data['corpus_preparation'], old.data['assessment_raw'])
    observation = reader.validate_definition_use_preservation_elaboration_packet_v2(*positional, **arguments)
    options = arguments | {'expected_elaboration_observation_sha256': sha(observation.observation_json.encode())}
    projection = projection_owner.prepare_definition_use_preservation_kernel_claims_v2(*positional, **options)
    bounds = protocols.ExecutionBounds(timeout_ms=60_000, max_steps=100_000,
        max_memory_bytes=2 * 1024**3, max_output_bytes=4 * 1024**2)
    return positional, options, projection, bounds


@pytest.fixture(scope='module')
def planned(inputs):
    positional, options, projection, bounds = inputs
    return owner.prepare_definition_use_preservation_kernel_requests_v2(
        projection, *positional, expected_projection_sha256=projection_owner.projection_sha256(projection),
        bounds=bounds, **options)


@pytest.fixture
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('planned requests attempted execution, observed usage, results or receipt issuance')
    monkeypatch.setattr(process.BoundedToolRunner, 'run', forbidden)
    monkeypatch.setattr(process, '_linux_owned_identity', forbidden)
    monkeypatch.setattr(native, 'build_definition_use_preservation_elaboration_native_v2', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(protocols.ProofReceipt, 'issue', forbidden)
    monkeypatch.setattr(protocols.BackendAttempt, '__init__', forbidden)
    monkeypatch.setattr(protocols.ResourceUsage, '__init__', forbidden)
    monkeypatch.setattr(protocols.ProofResult, 'for_attempt', forbidden)


def validate(prepared, inputs, **overrides):
    positional, options, projection, bounds = inputs
    return owner.validate_definition_use_preservation_kernel_requests_v2(
        prepared, projection, *positional,
        **({'expected_requests_sha256': sha(prepared.request_json.encode()),
            'expected_projection_sha256': projection_owner.projection_sha256(projection),
            'bounds': bounds} | options | overrides))


def test_public_request_import_is_stdlib_only():
    code = r'''
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','numpy','cryptography','multiformats','duckdb','requests')
class Deny:
    def find_spec(self,name,path=None,target=None):
        if any(name==item or name.startswith(item+'.') for item in blocked):
            raise AssertionError('operation import reached: '+name)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_cold_planned_kernel_requests',sys.argv[1])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
spec.loader.exec_module(module)
assert hasattr(module,'PlannedKernelTheoremRequests')
'''
    run = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code, owner.__file__],
                         capture_output=True, text=True, timeout=20, check=False)
    assert run.returncode == 0, run.stderr


def test_complete_planned_requests_replay_real_projection(inputs, planned, no_execution):
    assert validate(planned, inputs).request_json == planned.request_json
    _, _, projection, bounds = inputs
    document = planned.to_dict()
    assert document['request_count'] == len(planned.requests) == 15
    for path, pin in projection.to_dict()['producer_pins'].items():
        assert document['producer_pins'][path] == pin
    assert document['requests_prepared'] is document['backend_requests_prepared'] is True
    assert document['status'] == 'planned_requests_execution_not_qualified'
    for request, claim in zip(planned.requests, projection.claims, strict=True):
        assert type(request) is protocols.BackendRequest
        assert request.query_kind is protocols.QueryKind.THEOREM_PROOF
        assert request.claim_digest == claim.digest and request.declaration_id == claim.declaration_id
        assert request.obligation_digest == claim.obligations[0].digest
        assert request.assumption_ids == () and claim.assumptions == ()
        assert request.bounds == bounds and request.requested_backend_id == owner.BACKEND_ID
        payload = request.payload.to_dict()
        assert payload['kernel_proposition_json'] == claim.statement
        assert payload['encoding'] == owner.ENCODING
        assert payload['execution_profile_qualified'] is payload['dispatch_qualified'] is False
    assert sum(r.payload['quantified_proposition_premise_occurrences'] for r in planned.requests) == 5


def test_policy_does_not_fabricate_usage_or_authority(planned):
    value = planned.to_dict()
    assert all(value[name] is False for name in owner.FALSE_FLAGS)
    assert all(flag is False for flag in value['authority'].values())
    assert type(value['training_mask']) is type(value['evaluation_gold_mask']) is int
    assert value['training_mask'] == value['evaluation_gold_mask'] == 0
    policy = value['resource_policy']
    assert policy['status'] == 'execution_profile_not_qualified'
    assert policy['missing_measurement_may_be_represented_as_observed_zero'] is False
    assert policy['steps']['Lean_maxHeartbeats_is_whole_build_steps'] is False
    assert policy['peak_memory_bytes']['sampled_RSS_is_exact_peak'] is False
    assert policy['missing_metric_disposition'] == 'no affirmative theorem result or ProofReceipt'


@pytest.mark.parametrize('damage', ('statement', 'claim_digest', 'bounds', 'backend', 'query', 'external_assumption', 'zero_telemetry'))
def test_resealed_typed_request_mutants_refuse_current_regeneration(damage, inputs, planned, no_execution):
    requests = list(planned.requests)
    original = requests[0]
    if damage in ('statement', 'zero_telemetry'):
        payload = original.payload.to_dict()
        if damage == 'statement':
            payload['kernel_proposition_json'] = '{"type":"True"}'
        else:
            payload['resource_policy']['missing_measurement_may_be_represented_as_observed_zero'] = True
        requests[0] = replace(original, payload=FrozenMap(payload))
    elif damage == 'claim_digest':
        requests[0] = replace(original, claim_digest='0' * 64)
    elif damage == 'bounds':
        requests[0] = replace(original, bounds=replace(original.bounds, max_steps=1))
    elif damage == 'backend':
        requests[0] = replace(original, requested_backend_id='lean-kernel')
    elif damage == 'query':
        requests[0] = replace(original, query_kind=protocols.QueryKind.SATISFIABILITY)
    else:
        requests[0] = replace(original, assumption_ids=('invented_external_fact',))
    document = planned.to_dict()
    document['requests'] = [request.to_dict() for request in requests]
    document = corpus_contracts.seal_record({k: v for k, v in document.items() if k not in {'record_cid', 'cid_scope'}})
    changed = replace(planned, request_json=wire(document).decode(), requests=tuple(requests))
    with pytest.raises(ValueError):
        validate(changed, inputs)


def test_counterfeit_request_refuses_before_property_access(planned):
    accessed = []
    def poison(self):
        accessed.append(True)
        raise AssertionError('counterfeit request getter ran')
    spoof = type('BackendRequest', (), {'__module__': protocols.__name__, 'request_id': property(poison)})
    changed = replace(planned, requests=(spoof(), *planned.requests[1:]))
    with pytest.raises(ValueError):
        owner.request_sha256(changed)
    assert accessed == []


def test_resource_policy_global_mutation_refuses_before_replay(inputs, monkeypatch, no_execution):
    positional, options, projection, bounds = inputs
    changed = deepcopy(owner.RESOURCE_POLICY)
    changed['status'] = 'forged_qualified'
    monkeypatch.setattr(owner, 'RESOURCE_POLICY', changed)
    monkeypatch.setattr(projection_owner, 'validate_definition_use_preservation_kernel_claims_v2',
                        lambda *args, **kwargs: pytest.fail('projection replay reached changed fixed policy'))
    with pytest.raises(ValueError, match='fixed policy'):
        owner.prepare_definition_use_preservation_kernel_requests_v2(
            projection, *positional, expected_projection_sha256=projection_owner.projection_sha256(projection),
            bounds=bounds, **options)


def test_nominal_execution_bounds_refuses_before_getters(inputs):
    positional, options, projection, _ = inputs
    accessed = []
    def poison(self):
        accessed.append(True)
        raise AssertionError('counterfeit bounds getter ran')
    spoof = type('ExecutionBounds', (), {'__module__': protocols.__name__, 'timeout_ms': property(poison)})
    with pytest.raises(ValueError):
        owner.prepare_definition_use_preservation_kernel_requests_v2(
            projection, *positional, expected_projection_sha256=projection_owner.projection_sha256(projection),
            bounds=spoof(), **options)
    assert accessed == []


@pytest.mark.parametrize('field', ('payload', 'bounds', 'query_kind'))
def test_genuine_request_with_counterfeit_nested_storage_refuses_before_getters(field, planned):
    original = planned.requests[0]
    request = replace(original)
    assert type(request) is protocols.BackendRequest
    accessed = []
    def poison(self):
        accessed.append(field)
        raise AssertionError('counterfeit nested request descriptor executed')
    if field == 'payload':
        counterfeit = type('FrozenMap', (), {
            '__module__': FrozenMap.__module__, 'to_dict': property(poison),
        })
    elif field == 'bounds':
        counterfeit = type('ExecutionBounds', (), {
            '__module__': protocols.__name__, 'to_dict': property(poison),
        })
    else:
        counterfeit = type('QueryKind', (), {
            '__module__': protocols.__name__, 'value': property(poison),
        })
    # Bypass the frozen constructor only on a detached genuine outer request.
    # Refusal must happen before BackendRequest.to_dict traverses the poison.
    object.__setattr__(request, field, counterfeit())
    changed = replace(planned, requests=(request, *planned.requests[1:]))
    with pytest.raises(ValueError):
        owner.request_sha256(changed)
    assert accessed == []


def test_inherited_producer_pin_cannot_be_overwritten_after_genuine_projection_validation(
    inputs, monkeypatch, no_execution,
):
    positional, options, projection, bounds = inputs
    genuine_validator = projection_owner.validate_definition_use_preservation_kernel_claims_v2
    genuine_to_dict = projection_owner.KernelClaimProjection.to_dict
    completed = []
    source = str(Path(projection_owner.__file__).resolve())
    def incompatible_document(value):
        document = genuine_to_dict(value)
        assert source in document['producer_pins']
        document['producer_pins'][source] = '0' * 64
        return document
    def inject_after_actual_validation(*args, **kwargs):
        result = genuine_validator(*args, **kwargs)
        completed.append(result)
        # Simulate drift in the inherited pin at the immediate handoff without
        # editing any source file or altering the projection's pinned bytes.
        monkeypatch.setattr(projection_owner.KernelClaimProjection, 'to_dict', incompatible_document)
        return result
    monkeypatch.setattr(projection_owner, 'validate_definition_use_preservation_kernel_claims_v2',
                        inject_after_actual_validation)
    with pytest.raises(ValueError):
        owner.prepare_definition_use_preservation_kernel_requests_v2(
            projection, *positional, expected_projection_sha256=sha(projection.projection_json.encode()),
            bounds=bounds, **options)
    assert len(completed) == 1


@pytest.mark.parametrize('damage', ('depth', 'cycle'))
def test_projection_arguments_are_bounded_before_tree_digest_or_public_replay(
    damage, inputs, monkeypatch, no_execution,
):
    positional, options, projection, bounds = inputs
    changed = deepcopy(options)
    malformed = []
    if damage == 'depth':
        for _ in range(110):
            malformed = [malformed]
    else:
        malformed.append(malformed)
    changed['review_inputs']['reviews'] = malformed
    def premature(*args, **kwargs):
        pytest.fail('unbounded projection argument tree reached digest or public replay')
    monkeypatch.setattr(index_owner, '_tree_digest', premature)
    monkeypatch.setattr(projection_owner, 'validate_definition_use_preservation_kernel_claims_v2', premature)
    with pytest.raises(ValueError):
        owner.prepare_definition_use_preservation_kernel_requests_v2(
            projection, *positional, expected_projection_sha256=sha(projection.projection_json.encode()),
            bounds=bounds, **changed)


@pytest.mark.parametrize('name', ('SCHEMA', 'PROFILE', 'BACKEND_ID', 'ENCODING'))
def test_mutated_route_constants_refuse_before_projection_replay(name, inputs, monkeypatch, no_execution):
    positional, options, projection, bounds = inputs
    monkeypatch.setattr(owner, name, getattr(owner, name) + '-changed')
    monkeypatch.setattr(projection_owner, 'validate_definition_use_preservation_kernel_claims_v2',
                        lambda *args, **kwargs: pytest.fail('changed route constant reached projection replay'))
    with pytest.raises(ValueError):
        owner.prepare_definition_use_preservation_kernel_requests_v2(
            projection, *positional, expected_projection_sha256=sha(projection.projection_json.encode()),
            bounds=bounds, **options)
