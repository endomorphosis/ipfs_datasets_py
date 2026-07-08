"""Unit tests for the typed ``SecurityModelIR`` schema (PORTAL-CXTP-062).

These tests restore direct coverage of ``ir/schema.py`` and ``ir/canonicalize.py``:
construction, round-tripping, fail-closed validation of every typed
collection (assumptions, evidence, claims, proof obligations, disproof
vectors, runtime traces, solver results), and CID/canonicalization
stability.
"""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import (
    canonicalize_domain_coverage_report_json,
    canonicalize_ir,
    canonicalize_ir_json,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import (
    example_minimal_exchange_model,
    example_xaman_wallet_security_model,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    ALLOWED_PROVER_TARGETS,
    DISPROOF_VECTOR_STATUSES,
    KNOWN_SECURITY_DOMAINS,
    PROOF_OBLIGATION_STATUSES,
    PRODUCTION_SECURITY_DOMAINS,
    SOLVER_RESULT_VALUES,
    XAMAN_SECURITY_DOMAINS,
    SecurityModelIR,
    check_domain_coverage,
    claim_domains,
    domain_coverage_report,
    make_evidence_ref,
    validate_domain_coverage,
    validate_ir,
)


def _base_payload() -> dict:
    return example_minimal_exchange_model().to_dict()


# ---------------------------------------------------------------------------
# Construction / round-trip
# ---------------------------------------------------------------------------


def test_security_model_ir_has_typed_collections_with_defaults():
    model = SecurityModelIR(schema_version='security-model-ir/v1', model_id='t1')
    for field_name in (
        'claims',
        'proof_obligations',
        'disproof_vectors',
        'runtime_traces',
        'solver_results',
        'assumptions',
        'events',
    ):
        assert hasattr(model, field_name)
    assert model.claims == []
    assert model.proof_obligations == []
    assert model.disproof_vectors == []
    assert model.runtime_traces == []
    assert model.solver_results == []
    assert model.assumptions  # default threat-model assumptions populated


def test_to_dict_from_dict_round_trip_preserves_new_collections():
    model = example_minimal_exchange_model()
    payload = model.to_dict()
    restored = SecurityModelIR.from_dict(payload)
    assert restored.claims == model.claims
    assert restored.proof_obligations == model.proof_obligations
    assert restored.disproof_vectors == model.disproof_vectors
    assert restored.runtime_traces == model.runtime_traces
    assert restored.solver_results == model.solver_results


def test_from_untrusted_dict_strict_requires_all_typed_fields():
    payload = _base_payload()
    del payload['claims']
    with pytest.raises(ValueError, match='claims'):
        SecurityModelIR.from_untrusted_dict(payload, strict=True)


def test_from_untrusted_dict_strict_rejects_unknown_top_level_field():
    payload = _base_payload()
    payload['not_a_real_field'] = []
    with pytest.raises(ValueError, match='Unknown top-level'):
        SecurityModelIR.from_untrusted_dict(payload, strict=True)


def test_validate_ir_accepts_full_production_fixture():
    model = validate_ir(example_minimal_exchange_model())
    assert model.claims
    assert model.proof_obligations
    assert model.disproof_vectors
    assert model.runtime_traces
    assert model.solver_results


def test_validate_ir_accepts_full_xaman_fixture():
    model = validate_ir(example_xaman_wallet_security_model())
    assert model.claims
    assert {claim['domain'] for claim in model.claims} <= XAMAN_SECURITY_DOMAINS


# ---------------------------------------------------------------------------
# Domain vocabulary
# ---------------------------------------------------------------------------


def test_domain_constants_are_nonempty_and_related():
    assert PRODUCTION_SECURITY_DOMAINS
    assert XAMAN_SECURITY_DOMAINS
    assert KNOWN_SECURITY_DOMAINS == PRODUCTION_SECURITY_DOMAINS | XAMAN_SECURITY_DOMAINS


def test_claim_domains_helper_maps_ids_to_domains():
    model = example_minimal_exchange_model()
    mapping = claim_domains(model)
    assert mapping['claim:no_unauthorized_withdrawal'] == 'withdrawals'
    assert mapping['claim:global_asset_conservation'] == 'ledger'


# ---------------------------------------------------------------------------
# Claims validation
# ---------------------------------------------------------------------------


def test_claim_with_unknown_domain_is_rejected():
    payload = _base_payload()
    payload['claims'] = [
        {
            'id': 'claim:bogus',
            'description': 'A claim about a domain that does not exist.',
            'domain': 'not_a_real_domain',
        }
    ]
    payload['proof_obligations'] = []
    payload['disproof_vectors'] = []
    payload['solver_results'] = []
    with pytest.raises(ValueError, match='unknown security domain'):
        validate_ir(payload)


def test_claim_with_unknown_domain_allowed_when_marked_custom():
    payload = _base_payload()
    payload['claims'].append(
        {
            'id': 'claim:custom_domain_example',
            'description': 'A reviewed custom-domain claim outside the known vocabulary.',
            'domain': 'custom_domain',
            'custom': True,
        }
    )
    validate_ir(payload)  # should not raise


def test_claim_with_invalid_severity_is_rejected():
    payload = _base_payload()
    payload['claims'][0] = dict(payload['claims'][0], severity='catastrophic')
    with pytest.raises(ValueError, match='severity'):
        validate_ir(payload)


def test_duplicate_claim_ids_are_rejected():
    payload = _base_payload()
    payload['claims'].append(dict(payload['claims'][0]))
    with pytest.raises(ValueError, match='Duplicate claim'):
        validate_ir(payload)


def test_claim_evidence_refs_are_validated():
    payload = _base_payload()
    payload['claims'][0] = dict(
        payload['claims'][0],
        evidence_refs=[{'kind': 'not_a_kind', 'path': 'x', 'review_status': 'heuristic'}],
    )
    with pytest.raises(ValueError, match='Unsupported evidence ref kind'):
        validate_ir(payload)


# ---------------------------------------------------------------------------
# Proof obligations validation
# ---------------------------------------------------------------------------


def test_proof_obligation_references_unknown_claim():
    payload = _base_payload()
    payload['proof_obligations'].append(
        {
            'id': 'obligation:bogus',
            'claim_id': 'claim:does_not_exist',
            'prover': 'z3',
            'status': 'PROVED',
        }
    )
    with pytest.raises(ValueError, match='references unknown claim'):
        validate_ir(payload)


def test_proof_obligation_rejects_unsupported_status():
    payload = _base_payload()
    payload['proof_obligations'][0] = dict(payload['proof_obligations'][0], status='MAYBE')
    with pytest.raises(ValueError, match='unsupported status'):
        validate_ir(payload)


def test_proof_obligation_rejects_unsupported_prover():
    payload = _base_payload()
    payload['proof_obligations'][0] = dict(payload['proof_obligations'][0], prover='magic8ball')
    with pytest.raises(ValueError, match='unsupported prover'):
        validate_ir(payload)


def test_proof_obligation_statuses_match_module_constant():
    assert PROOF_OBLIGATION_STATUSES == frozenset({'PROVED', 'DISPROVED', 'UNKNOWN', 'NOT_MODELED'})


# ---------------------------------------------------------------------------
# Disproof vector validation
# ---------------------------------------------------------------------------


def test_disproof_vector_references_unknown_claim():
    payload = _base_payload()
    payload['disproof_vectors'].append(
        {
            'id': 'disproof:bogus',
            'claim_id': 'claim:does_not_exist',
            'tactic': 'invert_precondition',
            'status': 'SURVIVED',
        }
    )
    with pytest.raises(ValueError, match='references unknown claim'):
        validate_ir(payload)


def test_disproof_vector_rejects_unsupported_status():
    payload = _base_payload()
    payload['disproof_vectors'][0] = dict(payload['disproof_vectors'][0], status='MAYBE')
    with pytest.raises(ValueError, match='unsupported status'):
        validate_ir(payload)


def test_disproof_vector_statuses_include_disproved_survived_unknown():
    assert DISPROOF_VECTOR_STATUSES == frozenset({'DISPROVED', 'SURVIVED', 'UNKNOWN'})


# ---------------------------------------------------------------------------
# Solver results validation
# ---------------------------------------------------------------------------


def test_solver_result_references_unknown_claim():
    payload = _base_payload()
    payload['solver_results'].append(
        {
            'id': 'solver:bogus',
            'claim_id': 'claim:does_not_exist',
            'solver_name': 'z3',
            'result': 'unsat',
        }
    )
    with pytest.raises(ValueError, match='references unknown claim'):
        validate_ir(payload)


def test_solver_result_rejects_unsupported_result_value():
    payload = _base_payload()
    payload['solver_results'][0] = dict(payload['solver_results'][0], result='definitely-maybe')
    with pytest.raises(ValueError, match='unsupported result value'):
        validate_ir(payload)


def test_solver_result_values_are_lowercase_solver_vocabulary():
    assert SOLVER_RESULT_VALUES >= {'sat', 'unsat', 'unknown'}


# ---------------------------------------------------------------------------
# Runtime trace validation
# ---------------------------------------------------------------------------


def test_runtime_trace_references_unknown_event():
    payload = _base_payload()
    payload['runtime_traces'].append(
        {
            'id': 'trace:bogus',
            'description': 'References an event that was never modeled.',
            'events': ['event:does_not_exist'],
        }
    )
    with pytest.raises(ValueError, match='references unknown event id'):
        validate_ir(payload)


def test_runtime_trace_rejects_unknown_domain():
    payload = _base_payload()
    payload['runtime_traces'][0] = dict(payload['runtime_traces'][0], domain='not_a_real_domain')
    with pytest.raises(ValueError, match='unknown security domain'):
        validate_ir(payload)


def test_runtime_trace_requires_description():
    payload = _base_payload()
    payload['runtime_traces'].append({'id': 'trace:no_description', 'description': ''})
    with pytest.raises(ValueError, match='non-empty description'):
        validate_ir(payload)


# ---------------------------------------------------------------------------
# Domain coverage gate
# ---------------------------------------------------------------------------


def test_check_domain_coverage_reports_missing_domains():
    payload = _base_payload()
    payload['claims'] = [claim for claim in payload['claims'] if claim['domain'] != 'audit']
    payload['proof_obligations'] = [
        obligation for obligation in payload['proof_obligations'] if 'audit' not in obligation['claim_id']
    ]
    payload['solver_results'] = [
        result for result in payload['solver_results'] if 'audit' not in result['claim_id']
    ]
    payload['runtime_traces'] = [
        trace for trace in payload['runtime_traces'] if trace.get('domain') != 'audit'
    ]
    missing = check_domain_coverage(payload, required_domains=PRODUCTION_SECURITY_DOMAINS)
    assert missing == ['audit']


def test_validate_domain_coverage_raises_when_domain_missing():
    payload = _base_payload()
    payload['claims'] = [claim for claim in payload['claims'] if claim['domain'] != 'hsm']
    payload['proof_obligations'] = [
        obligation for obligation in payload['proof_obligations'] if 'wallet_freeze' not in obligation['claim_id']
    ]
    payload['solver_results'] = [
        result for result in payload['solver_results'] if 'wallet_freeze' not in result['claim_id']
    ]
    payload['disproof_vectors'] = [
        vector for vector in payload['disproof_vectors'] if 'wallet_freeze' not in vector['claim_id']
    ]
    with pytest.raises(ValueError, match='hsm'):
        validate_domain_coverage(payload, required_domains=PRODUCTION_SECURITY_DOMAINS)


def test_validate_domain_coverage_passes_for_full_fixture():
    model = validate_domain_coverage(
        example_minimal_exchange_model(), required_domains=PRODUCTION_SECURITY_DOMAINS
    )
    assert isinstance(model, SecurityModelIR)


def test_domain_coverage_report_lists_claim_ids_per_domain():
    report = domain_coverage_report(
        example_minimal_exchange_model(), required_domains=PRODUCTION_SECURITY_DOMAINS
    )
    assert report['fully_covered'] is True
    assert report['missing_domains'] == []
    assert report['domains']['withdrawals']['claim_ids'] == ['claim:no_unauthorized_withdrawal']


# ---------------------------------------------------------------------------
# CID / canonicalization
# ---------------------------------------------------------------------------


def test_canonicalize_ir_json_is_deterministic():
    model = example_minimal_exchange_model()
    first = canonicalize_ir_json(model)
    second = canonicalize_ir_json(copy.deepcopy(model))
    assert first == second


def test_canonicalize_ir_returns_utf8_bytes():
    model = example_minimal_exchange_model()
    payload = canonicalize_ir(model)
    assert isinstance(payload, bytes)
    payload.decode('utf-8')


def test_calculate_model_cid_is_stable_and_content_addressed():
    model = example_minimal_exchange_model()
    cid_a = calculate_model_cid(model)
    cid_b = calculate_model_cid(copy.deepcopy(model))
    assert cid_a == cid_b
    assert isinstance(cid_a, str) and cid_a


def test_calculate_model_cid_changes_when_content_changes():
    model = example_minimal_exchange_model()
    mutated_dict = model.to_dict()
    mutated_dict['claims'][0] = dict(mutated_dict['claims'][0], description='A materially different claim description.')
    mutated = SecurityModelIR.from_dict(mutated_dict)
    assert calculate_model_cid(model) != calculate_model_cid(mutated)


def test_canonicalize_domain_coverage_report_is_deterministic_json():
    model = example_minimal_exchange_model()
    first = canonicalize_domain_coverage_report_json(model, required_domains=PRODUCTION_SECURITY_DOMAINS)
    second = canonicalize_domain_coverage_report_json(model, required_domains=PRODUCTION_SECURITY_DOMAINS)
    assert first == second
    assert '"fully_covered":true' in first


def test_canonicalize_domain_coverage_report_fail_closed_raises_for_incomplete_model():
    model = example_xaman_wallet_security_model()
    with pytest.raises(ValueError):
        canonicalize_domain_coverage_report_json(
            model, required_domains=PRODUCTION_SECURITY_DOMAINS, fail_closed=True
        )


# ---------------------------------------------------------------------------
# Prover targets
# ---------------------------------------------------------------------------


def test_allowed_prover_targets_include_z3_and_documented_future_provers():
    assert 'z3' in ALLOWED_PROVER_TARGETS
    for prover in ('tla', 'tamarin', 'proverif', 'lean', 'coq', 'cvc5'):
        assert prover in ALLOWED_PROVER_TARGETS


def test_evidence_ref_helper_produces_required_fields():
    ref = make_evidence_ref(kind='source_code', path='src/x.py', review_status='heuristic')
    assert ref['kind'] == 'source_code'
    assert ref['path'] == 'src/x.py'
    assert ref['review_status'] == 'heuristic'
