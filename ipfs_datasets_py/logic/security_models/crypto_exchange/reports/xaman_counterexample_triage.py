"""Classify Xaman disproof and fuzz outputs without overstating their meaning."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-164'
SCHEMA_VERSION = 'xaman-counterexample-triage/v1'

SOURCE_SUPPORTED_DISPROOF_IDS = {
    'xaman-disproof:unsupported-xrpl-semantics',
}
MODEL_MUTATION_DISPROOF_IDS = {
    'xaman-disproof:assumption-mutation-native-vault',
    'xaman-disproof:auth-precondition-removal',
    'xaman-disproof:stale-evidence-acceptance',
    'xaman-disproof:wrong-network-signing',
    'xaman-disproof:replay-resolved-payload',
    'xaman-disproof:downgraded-solver-result',
}
EXTERNAL_EVIDENCE_DISPROOF_IDS = {
    'xaman-disproof:backend-double-use',
    'xaman-disproof:runtime-equivalence-missing',
}

FUZZ_DOMAIN_CLASSIFICATION = {
    'transaction_type_mutation': 'SOURCE_SUPPORTED_COVERAGE_GAP',
    'cancellation_expiry_reconnect_race': 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS',
    'replayed_payload': 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS',
    'malformed_payload': 'BOUNDARY_MODEL_MUTATION',
    'auth_review_bypass': 'BOUNDARY_MODEL_MUTATION',
    'wrong_network': 'BOUNDARY_MODEL_MUTATION',
    'account_import': 'BOUNDARY_MODEL_MUTATION',
    'stale_downgraded_evidence': 'PROOF_CONSUMER_CONTROL_MUTATION',
    'forged_finality': 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS',
    'solver_result_tampering': 'PROOF_CONSUMER_CONTROL_MUTATION',
}

SEVERITY_BY_CLASSIFICATION = {
    'SOURCE_SUPPORTED_COVERAGE_GAP': 1,
    'MODEL_MUTATION_CONTROL_TEST': 1,
    'PROOF_CONSUMER_CONTROL_MUTATION': 2,
    'BOUNDARY_MODEL_MUTATION': 2,
    'EXTERNAL_EVIDENCE_REQUIRED': 2,
    'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS': 3,
    'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION': 4,
    'UNCLASSIFIED_FAIL_CLOSED': 4,
}

NEXT_TASK_HINTS_BY_CLASSIFICATION = {
    'SOURCE_SUPPORTED_COVERAGE_GAP': ['PORTAL-CXTP-146', 'PORTAL-CXTP-147'],
    'MODEL_MUTATION_CONTROL_TEST': ['PORTAL-CXTP-070', 'PORTAL-CXTP-069'],
    'EXTERNAL_EVIDENCE_REQUIRED': ['PORTAL-CXTP-152', 'PORTAL-CXTP-153'],
    'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS': ['PORTAL-CXTP-150', 'PORTAL-CXTP-157'],
    'PROOF_CONSUMER_CONTROL_MUTATION': ['PORTAL-CXTP-073', 'PORTAL-CXTP-075'],
    'BOUNDARY_MODEL_MUTATION': ['PORTAL-CXTP-145', 'PORTAL-CXTP-147'],
    'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION': ['PORTAL-CXTP-165', 'PORTAL-CXTP-163'],
}

TRANSACTION_CLASS_HINTS = {
    'attack-offercreate-transaction-type': {
        'source_supported_tx_class': 'OfferCreate',
        'claim_id': 'xaman-testnet-claim:payload-intake-is-categorical-only',
        'next_tasks': ['PORTAL-CXTP-146', 'PORTAL-CXTP-147'],
    },
    'attack-signerlistset-transaction-type': {
        'source_supported_tx_class': 'SignerListSet',
        'claim_id': 'xaman-testnet-claim:payload-intake-is-categorical-only',
        'next_tasks': ['PORTAL-CXTP-146', 'PORTAL-CXTP-147'],
    },
    'attack-trustset-transaction-type': {
        'source_supported_tx_class': 'TrustSet',
        'claim_id': 'xaman-testnet-claim:payload-intake-is-categorical-only',
        'next_tasks': ['PORTAL-CXTP-146', 'PORTAL-CXTP-147'],
    },
}

MULTISIGN_CLASS_HINT = {
    'source_supported_tx_class': 'multisign',
    'claim_id': 'xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
    'next_tasks': ['PORTAL-CXTP-146', 'PORTAL-CXTP-147'],
}


def _triage_disproof(result: Mapping[str, Any]) -> dict[str, Any]:
    vector_id = str(result.get('vector_id'))
    if vector_id in SOURCE_SUPPORTED_DISPROOF_IDS:
        classification = 'SOURCE_SUPPORTED_COVERAGE_GAP'
        action = 'Keep the affected transaction classes proof-ineligible until semantic validation is implemented or explicitly rejected before signing.'
    elif vector_id in MODEL_MUTATION_DISPROOF_IDS:
        classification = 'MODEL_MUTATION_CONTROL_TEST'
        action = 'Keep the guard or evidence assumption explicit; reproduce against an unmodified runtime before treating this mutation as a product defect.'
    elif vector_id in EXTERNAL_EVIDENCE_DISPROOF_IDS:
        classification = 'EXTERNAL_EVIDENCE_REQUIRED'
        action = 'Obtain reviewed runtime/build evidence or an authorized backend contract; do not infer the missing behavior from public client source.'
    else:
        classification = 'UNCLASSIFIED_FAIL_CLOSED'
        action = 'Assign a human reviewer before any interpretation or assurance promotion.'
    return {
        'id': vector_id,
        'origin': 'disproof_vector',
        'classification': classification,
        'claim_id': result.get('claim_id'),
        'result': result.get('result'),
        'next_action': action,
        'confirmed_vulnerability': False,
    }


def _triage_fuzz(mutation: Mapping[str, Any]) -> dict[str, Any]:
    domain = str(mutation.get('fuzz_domain'))
    classification = FUZZ_DOMAIN_CLASSIFICATION.get(domain, 'UNCLASSIFIED_FAIL_CLOSED')
    if classification == 'SOURCE_SUPPORTED_COVERAGE_GAP':
        action = 'Retain the transaction class as proof-ineligible and add source validation or an explicit pre-signing rejection.'
    elif classification == 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS':
        action = 'Use a reviewed self-hosted runtime or authorized backend contract to model and test the affected lifecycle semantics.'
    elif classification == 'PROOF_CONSUMER_CONTROL_MUTATION':
        action = 'Maintain proof-consumer rejection tests and require reviewed evidence before acceptance.'
    elif classification == 'BOUNDARY_MODEL_MUTATION':
        action = 'Treat this as a model-boundary test; reproduce it against the unmodified public-source runtime before escalating.'
    else:
        action = 'Assign a human reviewer before any interpretation or assurance promotion.'
    return {
        'id': mutation.get('mutation_id'),
        'origin': 'fuzz_mutation',
        'classification': classification,
        'claim_id': mutation.get('target_claim_id'),
        'fuzz_domain': domain,
        'result': mutation.get('result'),
        'counterexample_path': mutation.get('counterexample_path'),
        'next_action': action,
        'confirmed_vulnerability': False,
    }


def _triage_native_vault_condition(condition: Mapping[str, Any]) -> dict[str, Any]:
    """Keep source-bound rekey states actionable without calling them defects."""

    classification = str(condition.get('classification'))
    if classification != 'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION':
        classification = 'UNCLASSIFIED_FAIL_CLOSED'
        action = 'Assign a human reviewer before interpreting this source-bound state result.'
    else:
        action = (
            'Under a valid independent verifier-only decision, inject the matching '
            'fault into an unmodified public-source runtime on Android and iOS; do not '
            'treat the bounded state as a product defect before reproduction.'
        )
    return {
        'id': condition.get('id'),
        'origin': 'native_vault_state_fuzz',
        'classification': classification,
        'summary': condition.get('summary'),
        'result': 'runtime_fault_injection_required',
        'next_action': action,
        'confirmed_vulnerability': False,
    }


def build_counterexample_triage(
    *,
    counterexample_report: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    transaction_coverage: Mapping[str, Any],
    native_vault_state_fuzz: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic interpretation boundary for all retained attacks."""

    disproof = [_triage_disproof(item) for item in counterexample_report.get('results', []) if isinstance(item, Mapping)]
    fuzz = [_triage_fuzz(item) for item in fuzz_report.get('attack_mutations', []) if isinstance(item, Mapping)]
    if native_vault_state_fuzz.get('task_id') != 'PORTAL-CXTP-167':
        raise ValueError('native-vault state fuzz input is not bound to PORTAL-CXTP-167')
    vault_conditions = [
        _triage_native_vault_condition(item)
        for item in native_vault_state_fuzz.get('source_supported_conditions', [])
        if isinstance(item, Mapping)
    ]
    entries = sorted([*disproof, *fuzz, *vault_conditions], key=lambda item: (str(item['origin']), str(item['id'])))
    counts = Counter(str(entry['classification']) for entry in entries)
    required_transaction_classes = {
        item.get('constraint')
        for item in transaction_coverage.get('constraint_coverage', [])
        if isinstance(item, Mapping) and item.get('status') == 'EXPLICITLY_REJECTED_FOR_PROOF'
    }
    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'inputs': {
            'counterexample_report_task_id': counterexample_report.get('task_id'),
            'fuzz_report_task_id': fuzz_report.get('task_id'),
            'transaction_coverage_task_id': transaction_coverage.get('task_id'),
            'transaction_coverage_artifact_cid': transaction_coverage.get('artifact_cid'),
            'native_vault_state_fuzz_task_id': native_vault_state_fuzz.get('task_id'),
            'native_vault_state_fuzz_artifact_cid': native_vault_state_fuzz.get('artifact_cid'),
        },
        'interpretation_policy': {
            'model_mutation_is_not_product_exploit': True,
            'fuzz_target_claim_trigger_is_not_product_exploit': True,
            'source_bounded_runtime_obligation_is_not_product_exploit': True,
            'source_supported_coverage_gap_blocks_proof_promotion': True,
            'every_entry_requires_fail_closed_handling': True,
        },
        'entries': entries,
        'summary': {
            'entry_count': len(entries),
            'classification_counts': dict(sorted(counts.items())),
            'confirmed_vulnerability_count': sum(1 for entry in entries if entry['confirmed_vulnerability']),
            'source_supported_coverage_gap_count': counts['SOURCE_SUPPORTED_COVERAGE_GAP'],
            'unmodeled_runtime_or_backend_semantics_count': counts['UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS'],
            'source_bounded_runtime_test_obligation_count': counts['SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION'],
            'required_proof_ineligible_transaction_classes': sorted(str(value) for value in required_transaction_classes if value),
        },
        'production_release_blocked': True,
        'overall_status': 'triaged_fail_closed',
        'security_decision': 'COUNTEREXAMPLES_TRIAGED_WITHOUT_PRODUCT_DEFECT_CLAIM',
    }
    report['artifact_cid'] = calculate_artifact_cid(report)
    return report


def _normalize_task_ids(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    unique: list[str] = []
    for value in values:
        value = str(value).strip()
        if not value:
            continue
        if value not in unique:
            unique.append(value)
    return sorted(unique)


def _entry_to_gap_item(entry: Mapping[str, Any]) -> dict[str, Any]:
    entry_id = str(entry.get('id'))
    classification = str(entry.get('classification'))
    claim_id = entry.get('claim_id')
    tx_class = ''
    next_actions: list[str] = []
    next_task_ids = _normalize_task_ids(NEXT_TASK_HINTS_BY_CLASSIFICATION.get(classification, []))
    remediation_note = (
        'No immediate product-defect claim without explicit runtime/evidence reproduction and review.'
    )

    if entry_id in TRANSACTION_CLASS_HINTS:
        hint = TRANSACTION_CLASS_HINTS[entry_id]
        tx_class = hint['source_supported_tx_class']
        claim_id = claim_id or hint['claim_id']
        next_task_ids = sorted(set(next_task_ids + hint['next_tasks']))
        next_actions = [
            f'Model {tx_class} support in XRPL transaction constraints and rerun disproof/fuzz assertions.',
            'Re-run PORTAL-CXTP-147 once syntax and coverage updates are committed.',
        ]
    elif classification == 'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION':
        tx_class = entry.get('summary') or ''
        remediation_note = (
            'Collect runtime fault-injection evidence for the matching unmodified public-source build.'
        )
        next_actions = [
            'Run CAPTURE evidence workflow (PORTAL-CXTP-165 and PORTAL-CXTP-163).',
            'Only close this item after both Android and reviewed iOS paths are represented.',
        ]
    elif classification == 'EXTERNAL_EVIDENCE_REQUIRED':
        next_actions = [
            'Request authorized backend/runtime/vendor evidence or testnet-to-production bridge artifacts.',
            'Do not map this item to a proof-lane promotion until evidence owner is known.',
        ]
        remediation_note = 'Requires external evidence with reviewer attestation and freshness.'
    elif classification == 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS':
        next_actions = [
            'Collect redacted runtime categories and backend contracts for the target claim.',
            'Feed observed evidence back into claim-to-source mappings before any claim promotion.',
        ]
        remediation_note = 'Runtime-obligation gap blocks proof promotion for this claim.'
    elif classification == 'BOUNDARY_MODEL_MUTATION':
        next_actions = [
            'Increase source-to-model boundary coverage and map to claim evidences.',
            'Reproduce as a boundary mutation on unmodified verifier-only runtime before escalation.',
        ]
        remediation_note = 'Treat as boundary migration before considering exploit interpretation.'
    elif classification == 'PROOF_CONSUMER_CONTROL_MUTATION':
        next_actions = [
            'Re-run proof-consumer verification and lock down evidence freshness checks.',
            'Update proof-consumer policies and keep this item blocked until tests remain passing.',
        ]
        remediation_note = 'Keep proof-consumer control invariants under explicit fail-closed policy.'
    elif classification == 'MODEL_MUTATION_CONTROL_TEST':
        next_actions = [
            'Tighten assumptions and re-run mutated proofs under the same solver profile.',
            'Record any new disproof witnesses as explicit assumptions before changing gating.',
        ]
        remediation_note = 'Model-mutation controls remain in review mode until source and assumptions are reconciled.'

    if entry_id == 'xaman-disproof:unsupported-xrpl-semantics':
        claim_id = claim_id or MULTISIGN_CLASS_HINT['claim_id']
        tx_class = MULTISIGN_CLASS_HINT['source_supported_tx_class']
        next_task_ids = sorted(set(next_task_ids + MULTISIGN_CLASS_HINT['next_tasks']))
        next_actions.append('Re-check transaction-class support matrix for OfferCreate/SignerListSet/TrustSet/multisign.')

    return {
        'entry_id': entry_id,
        'classification': classification,
        'claim_id': claim_id,
        'origin': entry.get('origin'),
        'source_supported_tx_class': tx_class or None,
        'priority': SEVERITY_BY_CLASSIFICATION.get(classification, 5),
        'next_task_ids': next_task_ids,
        'next_actions': next_actions or ['No automated action; keep as fail-closed source gap.'],
        'remediation_note': remediation_note,
    }


def build_gap_remediation_matrix(
    *,
    triage_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a ranked remediation matrix from triage classification."""

    if triage_report.get('task_id') != 'PORTAL-CXTP-164':
        raise ValueError('triage input is not bound to PORTAL-CXTP-164')
    if not isinstance(triage_report.get('entries'), list):
        raise ValueError('triage report is missing entries')

    entries = [_entry_to_gap_item(item) for item in triage_report['entries'] if isinstance(item, Mapping)]
    ranked = sorted(entries, key=lambda item: (item['priority'], str(item['classification']), str(item['entry_id'])))
    grouped = defaultdict(list)
    for item in ranked:
        grouped[item['classification']].append(item)

    for values in grouped.values():
        values.sort(key=lambda item: str(item['entry_id']))

    source_supported_tx = sorted(
        {
            item['source_supported_tx_class']
            for item in ranked
            if item['source_supported_tx_class'] in {'OfferCreate', 'SignerListSet', 'TrustSet', 'multisign'}
        }
    )
    required_tasks = sorted({task for item in ranked for task in item['next_task_ids']})
    report = {
        'schema_version': 'xaman-gap-remediation-matrix/v1',
        'task_id': 'PORTAL-CXTP-170',
        'generated_from_task_id': triage_report.get('task_id'),
        'generated_at_utc': '2026-07-19T00:00:00Z',
        'overall_status': 'remediation_required',
        'production_release_blocked': True,
        'security_decision': 'COUNTEREXAMPLES_REMEDIATION_PLAN_REQUIRED',
        'matrix_task_count': len(ranked),
        'required_task_ids': required_tasks,
        'source_supported_transaction_classes': source_supported_tx,
        'summary': {
            'entry_count': len(ranked),
            'classification_counts': dict(sorted(Counter(item['classification'] for item in ranked).items())),
            'highest_priority_classification': ranked[0]['classification'] if ranked else None,
            'required_task_count': len(required_tasks),
        },
        'grouped_by_classification': dict(sorted(grouped.items())),
        'matrix': ranked,
    }
    report['artifact_cid'] = calculate_artifact_cid(report)
    return report
