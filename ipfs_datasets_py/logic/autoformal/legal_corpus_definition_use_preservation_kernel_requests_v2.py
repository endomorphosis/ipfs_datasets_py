"""Prepare planned theorem requests from replayed closed kernel propositions.

These requests are data for a future qualified native execution profile. They
create no attempt, usage measurement, result or proof receipt. Their encoding
and prospective backend identifier deliberately distinguish them from the
existing single-source Lean adapter. Public import uses the standard library.
"""
from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from enum import EnumType
import hashlib
import json
import math
from pathlib import Path
import sys
from types import ModuleType

SCHEMA = 'legal-corpus-v2-preservation-planned-kernel-requests/v1'
PROFILE = 'planned-closed-kernel-theorem-requests/v1'
BACKEND_ID = 'legal-corpus-v2-closed-kernel-theorem-native@1'
ENCODING = 'lean4-kernel-proposition-json/v1'
MAX_RECORD_BYTES = 8 * 1024**2
MAX_REQUESTS = 15
PHYSICAL_WHOLE_PROJECT_RESOURCE_PROFILE = 'physical-whole-project-output/v1'
PHYSICAL_WHOLE_PROJECT_REQUEST_SCHEMA = 'legal-corpus-v4-planned-physical-whole-norm-request/v2'
# Existing physical packet allowance (48 MiB) plus the canonical live record (1 MiB).
# This ceiling applies to planning annotations, independent of native admission.
PHYSICAL_WHOLE_PROJECT_MAX_OUTPUT_BYTES = 49 * 1024**2
_PROTOCOLS = 'ipfs_datasets_py.logic.ir_core.protocols'
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
AUTHORITY = dict.fromkeys(('source', 'legal', 'review', 'proof', 'model', 'training', 'gold', 'corpus_admission'), False)
FALSE_FLAGS = dict.fromkeys((
    'execution_profile_qualified', 'backend_availability_probed', 'backend_executed',
    'native_execution_performed', 'compiler_probes_performed', 'resource_usage_observed',
    'step_limit_enforcement_qualified', 'memory_telemetry_qualified',
    'backend_attempt_created', 'proof_result_created', 'theorem_receipt_issued',
    'proof_checked', 'proof_authority', 'proof_usable', 'proof_cache_admission_verified',
    'cache_written', 'formalization_artifact_created', 'source_fidelity_proved',
    'legal_meaning_admitted', 'training_qualified', 'evaluation_gold_qualified',
    'model_convergence_proved', 'installed_stdlib_artifact_closure_verified',
), False)
RESOURCE_POLICY = {
    'schema': 'legal-corpus-v2-planned-kernel-request-resource-policy/v1',
    'status': 'execution_profile_not_qualified',
    'requested_bounds_are_measurements': False,
    'invocation_scope': 'one selected closed theorem per request; shared invocation mapping is not qualified',
    'elapsed_ms': {
        'unit': 'milliseconds', 'required_scope': 'whole native invocation including bounded cleanup',
        'measurement_required_before_affirmative_result': True,
        'clamping_observed_time_to_requested_bound_permitted': False,
    },
    'steps': {
        'unit': 'not_qualified', 'enforcement_method': 'not_qualified',
        'observation_method': 'not_qualified', 'required_coverage': 'explicitly defined request execution scope',
        'Lean_maxHeartbeats_is_whole_build_steps': False,
        'Lean_maxHeartbeats_units': 'thousands of internal allocation heartbeats per command',
        'zero_maxHeartbeats_permitted': False,
    },
    'peak_memory_bytes': {
        'unit': 'bytes', 'measurement_method': 'not_qualified',
        'aggregate_scope': 'not_qualified', 'sampled_RSS_is_exact_peak': False,
        'per_process_limits_are_hard_aggregate_limits': False,
    },
    'output_bytes': {
        'unit': 'bytes', 'required_scope': 'captured logs, returned artifacts, full type payload and result payload',
        'measurement_policy': 'complete accounting without truncation; exact accounting profile not qualified',
    },
    'required_observed_metrics': ['elapsed_ms', 'steps', 'peak_memory_bytes', 'output_bytes'],
    'missing_metric_disposition': 'no affirmative theorem result or ProofReceipt',
    'missing_measurement_may_be_represented_as_observed_zero': False,
    'genuinely_measured_zero_requires_explicit_coverage': True,
    'installed_stdlib_and_dynamic_libraries_are_external_trust_premises': True,
    'installed_stdlib_artifact_closure_verified': False,
}
_CONSTANTS_PIN = hashlib.sha256(json.dumps(
    {'schema': SCHEMA, 'profile': PROFILE, 'backend_id': BACKEND_ID, 'encoding': ENCODING,
     'max_record_bytes': MAX_RECORD_BYTES, 'max_requests': MAX_REQUESTS, 'protocols_module': _PROTOCOLS,
     'policy': RESOURCE_POLICY, 'authority': AUTHORITY, 'false_flags': FALSE_FLAGS,
     'physical_output_contract': [PHYSICAL_WHOLE_PROJECT_RESOURCE_PROFILE,
                                  PHYSICAL_WHOLE_PROJECT_REQUEST_SCHEMA,
                                  PHYSICAL_WHOLE_PROJECT_MAX_OUTPUT_BYTES]},
    sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    import re
    _need(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
          'independent lowercase SHA256 required: ' + label)


def _wire(value):
    from . import legal_corpus_definition_use_preservation_elaboration_native_v2 as native
    return native._wire(value, MAX_RECORD_BYTES)


def _parse(raw):
    from . import legal_corpus_definition_use_preservation_elaboration_native_v2 as native
    return native._parse(raw, MAX_RECORD_BYTES)


def _registered(name):
    module = sys.modules.get(_PROTOCOLS)
    _need(type(module) is ModuleType and vars(module).get('__name__') == _PROTOCOLS,
          'genuine registered theorem protocol module required')
    cls = vars(module).get(name)
    _need(type(cls) is (EnumType if name == 'QueryKind' else type)
          and cls.__module__ == _PROTOCOLS and cls.__name__ == name,
          'genuine registered theorem protocol class required')
    return cls


def _bounds_snapshot(bounds, *, output_limit=4 * 1024**2):
    _source_unchanged()
    cls = _registered('ExecutionBounds')
    _need(type(bounds) is cls, 'exact genuine finite ExecutionBounds required')
    value = {name: object.__getattribute__(bounds, name)
             for name in ('timeout_ms', 'max_steps', 'max_memory_bytes', 'max_output_bytes')}
    _need(set(value) == {'timeout_ms', 'max_steps', 'max_memory_bytes', 'max_output_bytes'}
          and all(type(v) is int and v > 0 for v in value.values())
          and value['timeout_ms'] <= 60_000 and value['max_steps'] <= 1_000_000_000
          and value['max_memory_bytes'] <= 2 * 1024**3 and value['max_output_bytes'] <= output_limit,
          'bounded proposed execution annotations required')
    return value


def _constants_unchanged():
    return _sha(_wire({'schema': SCHEMA, 'profile': PROFILE, 'backend_id': BACKEND_ID, 'encoding': ENCODING,
                       'max_record_bytes': MAX_RECORD_BYTES, 'max_requests': MAX_REQUESTS,
                       'protocols_module': _PROTOCOLS,
                       'policy': RESOURCE_POLICY, 'authority': AUTHORITY,
                       'false_flags': FALSE_FLAGS,
                       'physical_output_contract': [PHYSICAL_WHOLE_PROJECT_RESOURCE_PROFILE,
                                                    PHYSICAL_WHOLE_PROJECT_REQUEST_SCHEMA,
                                                    PHYSICAL_WHOLE_PROJECT_MAX_OUTPUT_BYTES]})) == _CONSTANTS_PIN


def _source_unchanged():
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN and _constants_unchanged(),
          'planned request owner or fixed policy changed since import')


def _requests_snapshot(requests):
    """Inspect genuine bounded nested storage without caller conversion methods."""
    _source_unchanged()
    _need(type(requests) is tuple and len(requests) == MAX_REQUESTS,
          'exact fifteen immutable planned theorem requests required')
    cls = _registered('BackendRequest')
    _need(all(type(request) is cls for request in requests),
          'genuine registered BackendRequest values required before slot access')
    claims_module_name = 'ipfs_datasets_py.logic.ir_core.claims'
    claims_module = sys.modules.get(claims_module_name)
    _need(type(claims_module) is ModuleType and vars(claims_module).get('__name__') == claims_module_name,
          'genuine registered frozen request metadata owner required')
    frozen = vars(claims_module).get('FrozenMap')
    _need(type(frozen) is ABCMeta and vars(frozen).get('__module__') == claims_module_name
          and type.__getattribute__(frozen, '__name__') == 'FrozenMap',
          'genuine registered frozen request metadata class required')
    query_cls = _registered('QueryKind')
    query_values = {
        'THEOREM_PROOF': 'theorem_proof', 'SATISFIABILITY': 'satisfiability',
        'RUNTIME_MONITOR': 'runtime_monitor', 'EVIDENCE_READINESS': 'evidence_readiness',
        'POLICY_APPROVAL': 'policy_approval',
    }
    query_members = vars(query_cls).get('_member_map_')
    _need(type(query_members) is dict, 'genuine query kind member storage required')
    budget, nodes = MAX_RECORD_BYTES, 500_000

    def visit(value, depth):
        nonlocal budget, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 80, 'bounded planned request storage node/depth required')
        kind = type(value)
        if value is None or kind is bool:
            budget -= 5
            item = value
        elif kind is str:
            _need('\x00' not in value and len(value) <= budget, 'bounded planned request storage text required')
            try:
                budget -= len(value.encode('utf-8')) + 2
            except UnicodeError as error:
                raise ValueError('valid planned request storage UTF8 required') from error
            item = value
        elif kind is int:
            _need(-(1 << 63) < value < (1 << 63), 'bounded planned request storage integer required')
            budget -= 20
            item = value
        elif kind is float:
            _need(math.isfinite(value), 'finite planned request storage number required')
            budget -= 32
            item = value
        elif kind is tuple:
            budget -= 2 + len(value)
            item = [visit(child, depth + 1) for child in value]
        elif kind is frozen:
            pairs = object.__getattribute__(value, '_items')
            _need(type(pairs) is tuple and len(pairs) <= 4096, 'bounded genuine frozen request metadata storage required')
            budget -= 2 + 2 * len(pairs)
            item, previous = {}, None
            for pair in pairs:
                _need(type(pair) is tuple and len(pair) == 2 and type(pair[0]) is str
                      and (previous is None or previous < pair[0]),
                      'canonical closed frozen request metadata keys required')
                previous = pair[0]
                item[visit(pair[0], depth + 1)] = visit(pair[1], depth + 1)
        else:
            raise ValueError('genuine recursively immutable request metadata required')
        _need(budget >= 0, 'complete planned request storage byte bound exceeded')
        return item

    result = []
    text_fields = ('request_id', 'claim_id', 'declaration_id', 'claim_digest', 'obligation_id',
                   'obligation_digest', 'logic_family', 'requested_backend_id', 'schema_version')
    for request in requests:
        row = {}
        for field in text_fields:
            value = object.__getattribute__(request, field)
            _need(type(value) is str and (bool(value) or field == 'requested_backend_id'),
                  'ordinary typed planned request text fields required')
            row[field] = visit(value, 0)
        _pin(row['claim_digest'], 'planned request claim')
        _pin(row['obligation_digest'], 'planned request obligation')
        _need(row['schema_version'] == 'proof-backend-request/v1', 'current planned request protocol schema required')
        assumptions = object.__getattribute__(request, 'assumption_ids')
        _need(type(assumptions) is tuple and len(assumptions) <= 4096
              and all(type(value) is str and value for value in assumptions),
              'closed unique planned request assumption IDs required')
        row['assumption_ids'] = visit(assumptions, 0)
        _need(len(set(row['assumption_ids'])) == len(assumptions),
              'closed unique planned request assumption IDs required')
        bounds = object.__getattribute__(request, 'bounds')
        row['bounds'] = _bounds_snapshot(bounds)
        payload = object.__getattribute__(request, 'payload')
        _need(type(payload) is frozen, 'genuine frozen planned request payload required before conversion')
        row['payload'] = visit(payload, 0)
        query = object.__getattribute__(request, 'query_kind')
        _need(type(query) is query_cls, 'genuine planned request query kind required before value access')
        member_name = object.__getattribute__(query, '_name_')
        member_value = object.__getattribute__(query, '_value_')
        _need(type(member_name) is str and member_name in query_values
              and query_members.get(member_name) is query
              and type(member_value) is str and member_value == query_values[member_name],
              'current genuine planned request query enum member required')
        row['query_kind'] = visit(member_value, 0)
        result.append(row)
    _wire(result)
    return result


@dataclass(frozen=True, slots=True)
class PlannedKernelTheoremRequests:
    request_json: str
    requests: tuple[object, ...]

    def to_dict(self):
        _need(type(self.request_json) is str and 0 < len(self.request_json) <= MAX_RECORD_BYTES,
              'bounded planned request document required')
        return _parse(self.request_json.encode('utf-8'))


def request_sha256(prepared):
    """Address exact consistent planned storage; computing a pin does not validate."""
    _source_unchanged()
    _need(type(prepared) is PlannedKernelTheoremRequests, 'exact planned theorem request storage required')
    value = PlannedKernelTheoremRequests.to_dict(prepared)
    _need(_wire(value.get('requests')) == _wire(_requests_snapshot(prepared.requests)),
          'serialized and typed planned request storage differ')
    return _sha(prepared.request_json.encode('utf-8'))


def prepare_definition_use_preservation_kernel_requests_v2(
        projection, native_packet_files, lineage, preservation_packet_files,
        corpus_preparation, assessment_raw, *, expected_projection_sha256, bounds,
        **projection_arguments):
    """Replay complete kernel/source custody and prepare fifteen non-executable requests."""
    _source_unchanged()
    _pin(expected_projection_sha256, 'complete kernel claim projection')
    bounds_before = _wire(_bounds_snapshot(bounds))
    from . import legal_corpus_definition_use_preservation_kernel_claims_v2 as owner
    from . import legal_corpus_definition_use_preservation_elaboration_packet_v2 as reader
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as header
    from . import legal_corpus_definition_use_preservation_packet_v2 as original_reader
    from . import legal_corpus_definition_use_preservation_index_v2 as index
    from . import corpus_contracts as contracts
    from ..ir_core import protocols
    operation_producers = {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).resolve().read_bytes())
        for module in (owner, reader, header, original_reader, index, contracts, protocols)
    }

    def arguments_digest():
        original_reader._bound_tree(projection_arguments, original_reader.MAX_INPUT_BYTES, allow_bytes=True)
        return index._tree_digest(projection_arguments)

    arguments_before = arguments_digest()
    projection_before = owner.projection_sha256(projection)
    native_before = reader.packet_sha256(native_packet_files)
    original_before = original_reader.packet_sha256(preservation_packet_files)
    lineage_before = header.lineage_sha256(lineage)
    corpus_before = original_reader._wire(original_reader._corpus_document(corpus_preparation),
                                         20 * original_reader.MAX_RECORD_BYTES)
    checked = owner.validate_definition_use_preservation_kernel_claims_v2(
        projection, native_packet_files, lineage, preservation_packet_files,
        corpus_preparation, assessment_raw, expected_projection_sha256=expected_projection_sha256,
        **projection_arguments)
    _source_unchanged()
    _need(arguments_digest() == arguments_before
          and _wire(_bounds_snapshot(bounds)) == bounds_before
          and all(_sha(Path(path).read_bytes()) == pin for path, pin in operation_producers.items()),
          'planned request arguments, bounds or producer identities changed during projection replay')
    _need(owner.projection_sha256(checked) == projection_before == expected_projection_sha256,
          'planned requests require exact complete current kernel projection')
    document = checked.to_dict()
    resource_policy = _parse(_wire(RESOURCE_POLICY))
    resource_pin = _sha(_wire(resource_policy))
    bounds_document = _bounds_snapshot(bounds)
    owned_bounds = protocols.ExecutionBounds(**bounds_document)
    context = {
        'profile': PROFILE, 'kernel_projection_sha256': expected_projection_sha256,
        'complete_projection_arguments_sha256': arguments_before,
        'native_bundle_sha256': native_before, 'preservation_packet_bundle_sha256': original_before,
        'source_lineage_sha256': lineage_before, 'bounds': bounds_document,
        'requested_backend_id': BACKEND_ID, 'encoding': ENCODING,
        'resource_policy_sha256': resource_pin,
    }
    context_pin = _sha(_wire(context))
    requests, entries = [], []
    for entry, claim in zip(document['entries'], checked.claims, strict=True):
        _need(claim.assumptions == () and len(claim.obligations) == 1
              and claim.obligations[0].assumption_ids == ()
              and entry['external_assumption_ids'] == [], 'whole quantified kernel targets required')
        obligation = claim.obligations[0]
        key = _sha(_wire({'context_sha256': context_pin, 'claim_digest': claim.digest,
                         'obligation_digest': obligation.digest}))
        payload = {
            'schema': 'legal-corpus-v2-planned-kernel-theorem-request-payload/v1',
            'profile': PROFILE, 'encoding': ENCODING,
            'kernel_proposition_json': claim.statement,
            'kernel_statement_sha256': entry['kernel_statement_sha256'],
            'kernel_context_sha256': entry['kernel_context_sha256'],
            'semantic_context_sha256': document['semantic_context_sha256'],
            'kernel_projection_sha256': expected_projection_sha256,
            'request_context_sha256': context_pin,
            'theorem_name': entry['theorem_name'], 'source_namespace': entry['source_namespace'],
            'quantified_proposition_premise_occurrences': len(entry['proposition_premise_associations']),
            'external_assumption_count': 0,
            'target_scope': 'complete closed quantified kernel proposition; bound hypotheses remain quantified',
            'resource_policy': resource_policy, 'resource_policy_sha256': resource_pin,
            'execution_profile_qualified': False, 'dispatch_qualified': False,
            'shared_invocation_mapping_qualified': False,
            'installed_stdlib_artifact_closure_verified': False,
        }
        request = protocols.BackendRequest.for_claim(
            claim, obligation.obligation_id, request_id='planned_kernel_request:' + key,
            query_kind=protocols.QueryKind.THEOREM_PROOF, bounds=owned_bounds,
            payload=payload, requested_backend_id=BACKEND_ID)
        requests.append(request)
        entries.append({
            'theorem_name': entry['theorem_name'], 'claim_id': claim.claim_id,
            'claim_digest': claim.digest, 'declaration_id': claim.declaration_id,
            'obligation_id': obligation.obligation_id, 'obligation_digest': obligation.digest,
            'request_id': request.request_id, 'request_digest': request.digest,
            'kernel_statement_sha256': entry['kernel_statement_sha256'],
            'quantified_proposition_premise_occurrences': len(entry['proposition_premise_associations']),
            'external_assumption_ids': [],
        })
    _need(len(requests) == MAX_REQUESTS and len({item.digest for item in requests}) == MAX_REQUESTS,
          'exact distinct fifteen planned theorem requests required')
    producers = dict(document['producer_pins'])
    for path, pin in operation_producers.items():
        _need((path not in producers or producers[path] == pin)
              and _sha(Path(path).read_bytes()) == pin,
              'current request producer differs from inherited kernel projection producer pin')
        producers[path] = pin
    _need(str(Path(__file__).resolve()) not in producers
          or producers[str(Path(__file__).resolve())] == _SELF_PIN,
          'planned request owner differs from inherited projection producer pin')
    producers[str(Path(__file__).resolve())] = _SELF_PIN
    request_rows = _requests_snapshot(tuple(requests))
    record = contracts.seal_record({
        'schema': SCHEMA, **context, 'request_context_sha256': context_pin,
        'resource_policy': resource_policy, 'requests': request_rows,
        'entries': entries, 'request_count': MAX_REQUESTS,
        'quantified_proposition_premise_occurrences': document['proposition_premise_association_count'],
        'external_assumption_count': 0, 'producer_pins': producers,
        'requests_prepared': True, 'backend_requests_prepared': True, 'dispatch_qualified': False,
        'status': 'planned_requests_execution_not_qualified',
        'trust_boundary': [
            'The public kernel projection validator replays complete current source/review and retained packet inputs.',
            'THEOREM_PROOF is requested, not granted. No BackendAttempt, ResourceUsage, result or ProofReceipt is constructed.',
            'The prospective backend identifier and kernel JSON encoding have no qualified execution adapter in this profile.',
            'Finite requested bounds are annotations, not evidence of enforcement or measured usage. Missing steps or memory telemetry cannot become observed zero.',
            'Whole closed types retain quantified hypotheses; empty external assumption IDs do not establish those hypotheses as facts.',
            'Installed standard and dynamically loaded compiler libraries remain explicit external trust premises.',
        ],
        'authority': dict(AUTHORITY), 'training_mask': 0, 'evaluation_gold_mask': 0, **FALSE_FLAGS,
    })
    _need(arguments_digest() == arguments_before
          and _wire(_bounds_snapshot(bounds)) == bounds_before
          and owner.projection_sha256(projection) == projection_before
          and reader.packet_sha256(native_packet_files) == native_before
          and original_reader.packet_sha256(preservation_packet_files) == original_before
          and header.lineage_sha256(lineage) == lineage_before
          and original_reader._wire(original_reader._corpus_document(corpus_preparation),
                                   20 * original_reader.MAX_RECORD_BYTES) == corpus_before
          and _wire(RESOURCE_POLICY) == _wire(resource_policy)
          and _constants_unchanged()
          and all(_sha(Path(path).read_bytes()) == pin for path, pin in producers.items())
          and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
          'planned request inputs or producer identities changed during preparation')
    result = PlannedKernelTheoremRequests(_wire(record).decode('utf-8'), tuple(requests))
    request_sha256(result)
    return result


def validate_definition_use_preservation_kernel_requests_v2(
        prepared, projection, native_packet_files, lineage, preservation_packet_files,
        corpus_preparation, assessment_raw, *, expected_requests_sha256,
        expected_projection_sha256, bounds, **projection_arguments):
    """Regenerate every planned request and compare typed, type-sensitive storage."""
    _pin(expected_requests_sha256, 'complete planned request document')
    original = request_sha256(prepared)
    _need(original == expected_requests_sha256, 'independent planned request pin differs')
    document = PlannedKernelTheoremRequests.to_dict(prepared)
    _need(document.get('schema') == SCHEMA and document.get('profile') == PROFILE
          and all(document.get(field) is False for field in FALSE_FLAGS)
          and document.get('authority') == AUTHORITY and all(v is False for v in document['authority'].values())
          and type(document.get('training_mask')) is type(document.get('evaluation_gold_mask')) is int
          and document['training_mask'] == document['evaluation_gold_mask'] == 0,
          'closed non-authorizing planned request document required')
    regenerated = prepare_definition_use_preservation_kernel_requests_v2(
        projection, native_packet_files, lineage, preservation_packet_files,
        corpus_preparation, assessment_raw, expected_projection_sha256=expected_projection_sha256,
        bounds=bounds, **projection_arguments)
    _need(request_sha256(prepared) == original == request_sha256(regenerated)
          and prepared.request_json.encode() == regenerated.request_json.encode()
          and _wire(_requests_snapshot(prepared.requests)) == _wire(_requests_snapshot(regenerated.requests)),
          'complete current planned theorem requests differ from regeneration')
    return regenerated


__all__ = ['PlannedKernelTheoremRequests', 'request_sha256',
           'prepare_definition_use_preservation_kernel_requests_v2',
           'validate_definition_use_preservation_kernel_requests_v2']


def prepare_reviewed_physical_whole_norm_kernel_request_v2(
        preparation, preservation, graph, admission, *args, expected_realization_sha256,
        expected_theorem, expected_unit_id, bounds, resource_profile=None, **realization_arguments):
    """Plan one conditional theorem request in a fully replayed physical V2 project.

    The proposition is Lean source scoped to its original project namespace.
    The request carries project commitments, not an elaborated kernel type or
    an executable single-file Lean input. Opting into whole-project accounting
    selects an aggregate output annotation over the original retained packet
    and canonical live result. It does not grant native admission.
    """
    from . import legal_corpus_shared_lake as shared
    from ..ir_core import claims, protocols

    _need(resource_profile is None or (
        type(resource_profile) is str and resource_profile == PHYSICAL_WHOLE_PROJECT_RESOURCE_PROFILE),
        'exact physical whole-project resource profile required')
    whole_project_output = resource_profile is not None
    output_limit = PHYSICAL_WHOLE_PROJECT_MAX_OUTPUT_BYTES if whole_project_output else 4 * 1024**2
    owned_bounds = protocols.ExecutionBounds(**_bounds_snapshot(bounds, output_limit=output_limit))
    _need(type(expected_theorem) is str and bool(expected_theorem)
          and type(expected_unit_id) is str and bool(expected_unit_id),
          'independently selected qualified theorem and reviewed unit required')
    verified = shared.validate_reviewed_physical_definition_realization_corpus_v2(
        preparation, preservation, graph, admission, *args,
        expected_realization_sha256=expected_realization_sha256, **realization_arguments)
    manifest = verified.to_dict()
    _need(expected_theorem in manifest['definition_application_obligations'],
          'selected theorem is outside the verified physical definition application')
    entry = next(row for row in manifest['theorem_bindings'] if row['theorem'] == expected_theorem)
    binding = entry['binding']
    _need(binding['kind'] == 'whole_norm_definition_expansion'
          and binding['unit_id'] == expected_unit_id
          and binding['premise_kind'] == 'independently_denoted_source_definition'
          and binding['desired_equivalence_hypothesis'] is False,
          'selected theorem is not the conditional whole-norm obligation for the reviewed unit')

    unit = next(row for row in manifest['units'] if row['unit_id'] == expected_unit_id)
    selection = manifest['selection']
    definition = next(row for row in manifest['units'] if row['unit_id'] == selection['definition_unit_id'])
    module, _, theorem = expected_theorem.rpartition('.')
    module_path = module.replace('.', '/') + '.lean'
    files = dict(verified.files)
    source = files[module_path]
    abi = shared._reviewed_definition_application_abi_example(unit, definition['instance_module'])
    prefix, suffix = 'example : ', ' := @' + theorem + '\n'
    _need(module in manifest['expected_modules'] and source.startswith('import ')
          and source.count('\nnamespace ' + module + '\n') == 1
          and source.count('\n' + entry['declaration'] + ' := by\n') == 1
          and abi.startswith(prefix) and abi.endswith(suffix) and source.count('\n' + abi) == 1,
          'exact project declaration and independent proposition consumer required')
    proposition = abi[len(prefix):-len(suffix)]

    context = {
        'realization_sha256': expected_realization_sha256,
        'realization_input_commitment_sha256': manifest['input_commitment_sha256'],
        'physical_context_sha256': manifest['physical_context_sha256'],
        'physical_request_sha256': manifest['physical_context']['physical_request_sha256'],
        'preservation_sha256': manifest['reviewed_preservation_sha256'],
        'graph_sha256': manifest['reviewed_graph_sha256'],
        'admission_sha256': manifest['reviewed_admission_sha256'],
        'declaration_sha256': manifest['declaration_sha256'],
        'theorem': expected_theorem,
        'theorem_binding': binding,
        'source_namespace': module,
        'source_path': module_path,
        'proposition_utf8_sha256': _sha(proposition.encode('utf-8')),
        'unit': {field: unit[field] for field in (
            'unit_id', 'complete_ir_sha256', 'source_occurrence_cid', 'source_version_cid',
            'interpretation_record_cid', 'scope_record_cid', 'relational_request_sha256',
            'source_use_binding_sha256')},
        'source_definition': {field: definition[field] for field in (
            'unit_id', 'complete_ir_sha256', 'source_occurrence_cid', 'source_version_cid',
            'interpretation_record_cid', 'scope_record_cid', 'source_use_binding_sha256')},
    }
    context_sha256 = _sha(_wire(context))
    refs = tuple(dict.fromkeys((unit['source_occurrence_cid'], definition['source_occurrence_cid'])))
    obligation = claims.ProofObligation(
        obligation_id='physical_whole_norm_obligation:' + context_sha256,
        statement=proposition, logic_family='lean4', source_refs=refs, metadata=context)
    claim = claims.IRClaim(
        claim_id='physical_whole_norm_claim:' + context_sha256, statement=proposition,
        assumptions=(), obligations=(obligation,), domain='legal-ir',
        declaration_id=expected_theorem, source_refs=refs)
    request_identity = {'context_sha256': context_sha256, 'bounds': owned_bounds.to_dict()}
    resource_policy = RESOURCE_POLICY
    schema = 'legal-corpus-v4-planned-physical-whole-norm-request/v1'
    profile_fields = {}
    if whole_project_output:
        request_identity['resource_profile'] = resource_profile
        profile_fields['resource_profile'] = resource_profile
        schema = PHYSICAL_WHOLE_PROJECT_REQUEST_SCHEMA
        resource_policy = {
            **RESOURCE_POLICY,
            'invocation_scope': 'original whole physical project for one selected conditional theorem',
            'output_bytes': {
                'unit': 'bytes',
                'required_scope': 'uncompressed retained packet members once per path and canonical sealed live result',
                'accounting_profile': resource_profile,
                'measurement_policy': 'exact post-capture logical bytes without archive or runner transport wrappers',
                'plan_ceiling_bytes': PHYSICAL_WHOLE_PROJECT_MAX_OUTPUT_BYTES,
                'per_file_or_stream_ceiling_is_an_aggregate_bound': False,
                'full_elaborated_type_payload_available': False,
            },
        }
    request = protocols.BackendRequest.for_claim(
        claim, obligation.obligation_id,
        request_id='planned_physical_whole_norm:' + _sha(_wire(request_identity)),
        query_kind=protocols.QueryKind.THEOREM_PROOF, bounds=owned_bounds,
        requested_backend_id='legal-corpus-v4-physical-project-kernel@1',
        payload={
            'schema': schema,
            **profile_fields,
            'encoding': 'lean4-physical-project-proposition-source/v1',
            'context': context, 'context_sha256': context_sha256,
            'proposition_source': proposition,
            'project': {
                'target': manifest['target'], 'toolchain': manifest['toolchain'],
                'expected_modules': manifest['expected_modules'],
                'module_imports': manifest['module_imports'],
                'files': [{
                    'path': path, 'bytes': len(body.encode('utf-8')),
                    'sha256': manifest['file_sha256'][path],
                } for path, body in verified.files],
            },
            'premise_remains_quantified': True,
            'elaborated_type_verified': False,
            'dispatch_qualified': False,
            'execution_profile_qualified': False,
            'resource_policy': resource_policy,
            'authority': AUTHORITY,
            'training_mask': 0, 'evaluation_gold_mask': 0,
        })
    return claim, request


__all__ += ['prepare_reviewed_physical_whole_norm_kernel_request_v2']
