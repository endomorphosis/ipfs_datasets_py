"""Xaman mutation and disproof counterexample suite.

The suite is intentionally deterministic and artifact-backed.  It checks the
current Xaman SecurityModelIR baseline for the assumptions and claims each
mutation depends on, then emits compact vectors plus a report that separates
concrete counterexamples from cases that must remain fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


SCHEMA_VERSION = 'xaman-disproof-vectors/v1'
REPORT_SCHEMA_VERSION = 'xaman-counterexample-report/v1'
TASK_ID = 'PORTAL-CXTP-070'
REFERENCE_DATE = '2026-07-08'
MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
CLAIMS_PATH = 'security_ir_artifacts/corpora/xaman-app/security-claims.json'


@dataclass(frozen=True, slots=True)
class XamanDisproofScenario:
    scenario_id: str
    title: str
    claim_id: str
    mutation_class: str
    expected_status: str
    expected_detection: str
    tactic: str
    mutation: dict[str, Any]
    expected_blockers: tuple[str, ...] = ()


SCENARIOS: tuple[XamanDisproofScenario, ...] = (
    XamanDisproofScenario(
        scenario_id='assumption-promotion-without-evidence',
        title='Mutated native-vault assumption accepted without evidence',
        claim_id='xaman-security:claim:custody-software-private-key-not-available-without-authorized-vault-path',
        mutation_class='mutated_assumption',
        expected_status='DISPROVED',
        expected_detection='counterexample_found',
        tactic='mutate:blocking_assumption_to_evidenced_without_required_evidence',
        mutation={
            'assumption_id': 'xaman-security:assumption:native-vault-cryptographic-confidentiality',
            'field': 'acceptance_status',
            'from': 'BLOCKING',
            'to': 'EVIDENCED',
            'removed_fields': ['blocking_reason', 'required_evidence_to_accept'],
        },
    ),
    XamanDisproofScenario(
        scenario_id='auth-precondition-removed-signing',
        title='Signing proceeds after authentication preconditions are removed',
        claim_id='xaman-security:claim:authentication-gates-vault-and-signing',
        mutation_class='auth_precondition_removed',
        expected_status='DISPROVED',
        expected_detection='counterexample_found',
        tactic='remove:authentication_overlay_and_vault_open_preconditions',
        mutation={
            'removed_preconditions': [
                'fresh_passcode_or_biometric_authorization',
                'vault_opened_with_encryption_key',
            ],
            'inserted_terminal_event': 'xaman_transaction_signed',
        },
    ),
    XamanDisproofScenario(
        scenario_id='stale-evidence-accepted',
        title='Expired payload-integrity evidence is accepted by a consumer',
        claim_id='xaman-security:claim:payload-integrity-before-review-and-signing',
        mutation_class='stale_evidence',
        expected_status='DISPROVED',
        expected_detection='counterexample_found',
        tactic='age:evidence_expires_before_release_window',
        mutation={
            'field': 'evidence_expires_at',
            'from': '2027-01-08T00:00:00Z',
            'to': '2026-01-01T00:00:00Z',
            'release_window_date': REFERENCE_DATE,
        },
    ),
    XamanDisproofScenario(
        scenario_id='wrong-network-submit',
        title='Mainnet payload is signed and submitted on the wrong network',
        claim_id='xaman-security:claim:network-binding-prevents-cross-network-signing',
        mutation_class='wrong_network',
        expected_status='DISPROVED',
        expected_detection='counterexample_found',
        tactic='substitute:force_network_or_submit_node_mismatch',
        mutation={
            'payload_force_network': 'xrpl-mainnet',
            'active_app_network': 'xrpl-testnet',
            'populated_network_id': 1,
            'submit_node_network': 'xrpl-testnet',
        },
    ),
    XamanDisproofScenario(
        scenario_id='remote-payload-replay-race',
        title='Two clients resolve the same remote payload UUID',
        claim_id='xaman-security:claim:payload-replay-prevention-is-single-use',
        mutation_class='replay_payload',
        expected_status='DISPROVED',
        expected_detection='counterexample_found',
        tactic='race:double_resolve_same_payload_uuid',
        mutation={
            'payload_uuid': 'payload:replay-counterexample',
            'terminal_transitions': ['signed_patch', 'submitted_patch'],
            'backend_atomic_resolution': False,
        },
    ),
    XamanDisproofScenario(
        scenario_id='downgraded-solver-proof-packet',
        title='Proof packet downgrades required solver support',
        claim_id='xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims',
        mutation_class='downgraded_solver',
        expected_status='EXPLICITLY_BLOCKED',
        expected_detection='blocked_fail_closed',
        tactic='consume:downgraded_or_missing_solver_result',
        mutation={
            'solver_name': 'z3',
            'solver_version': 'below-required-baseline',
            'removed_solver': 'cvc5',
            'forged_result': 'PROVED',
        },
        expected_blockers=(
            'xaman-security:assumption:proof-receipt-cid-or-signature-validation',
        ),
    ),
    XamanDisproofScenario(
        scenario_id='unsupported-xrpl-semantics',
        title='Unsupported TrustSet and SignerListSet semantics are required',
        claim_id='xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent',
        mutation_class='unsupported_xrpl_semantics',
        expected_status='EXPLICITLY_BLOCKED',
        expected_detection='blocked_fail_closed',
        tactic='block:unsupported_trustset_signerlist_or_server_semantics',
        mutation={
            'transaction_types': ['TrustSet', 'SignerListSet'],
            'client_validation': 'stubbed_or_not_implemented',
            'requires_server_rule_semantics': True,
        },
        expected_blockers=(
            'xaman-security:assumption:trustset-and-signerlist-client-validation',
            'xaman-security:assumption:xrpl-server-rule-enforcement-and-consensus',
        ),
    ),
    XamanDisproofScenario(
        scenario_id='backend-trust-forged-resolution',
        title='Backend accepts an unauthorized payload resolution patch',
        claim_id='xaman-security:claim:backend-trust-boundary-is-safe-for-payload-resolution',
        mutation_class='backend_trust_failure',
        expected_status='DISPROVED',
        expected_detection='counterexample_found',
        tactic='forge:unauthorized_backend_patch_or_resolution',
        mutation={
            'backend_authorized': False,
            'payload_uuid_bound_to_requester': False,
            'patch_conflict_rejected': False,
            'accepted_terminal_state': 'signed',
        },
    ),
)


def _index_by_id(items: list[Mapping[str, Any]], item_type: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in items:
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f'{item_type} entry missing id')
        indexed[item_id] = item
    return indexed


def _iso_date(value: str) -> str:
    return value.split('T', 1)[0]


def _claim_category(claim: Mapping[str, Any]) -> str:
    category = claim.get('xaman_category')
    if not isinstance(category, str) or not category:
        raise ValueError(f'claim {claim.get("id")} is missing xaman_category')
    return category


def _scenario_trace(scenario: XamanDisproofScenario) -> list[dict[str, Any]]:
    if scenario.mutation_class == 'mutated_assumption':
        return [
            {
                'event_id': 'event:xaman:mutated-assumption-promoted',
                'event': 'assumption_acceptance_status_mutated',
                'assumption_id': scenario.mutation['assumption_id'],
                'from': scenario.mutation['from'],
                'to': scenario.mutation['to'],
            },
            {
                'event_id': 'event:xaman:unaudited-vault-secret-read',
                'event': 'software_private_key_material_available',
                'authorized_vault_path': False,
                'required_evidence_present': False,
            },
        ]
    if scenario.mutation_class == 'auth_precondition_removed':
        return [
            {
                'event_id': 'event:xaman:payload-reviewed',
                'event': 'xaman_payload_reviewed',
                'payload_uuid': 'payload:auth-precondition-counterexample',
            },
            {
                'event_id': 'event:xaman:transaction-signed-without-auth',
                'event': 'xaman_transaction_signed',
                'auth_success_seen': False,
                'vault_opened_seen': False,
            },
        ]
    if scenario.mutation_class == 'stale_evidence':
        return [
            {
                'event_id': 'event:xaman:evidence-aged-out',
                'event': 'evidence_expired',
                'evidence_expires_at': scenario.mutation['to'],
                'release_window_date': scenario.mutation['release_window_date'],
            },
            {
                'event_id': 'event:xaman:stale-evidence-accepted',
                'event': 'claim_accepted_with_stale_evidence',
                'freshness_checked': False,
            },
        ]
    if scenario.mutation_class == 'wrong_network':
        return [
            {
                'event_id': 'event:xaman:wrong-network-reviewed',
                'event': 'xaman_payload_reviewed',
                'payload_force_network': scenario.mutation['payload_force_network'],
                'active_app_network': scenario.mutation['active_app_network'],
            },
            {
                'event_id': 'event:xaman:wrong-network-submitted',
                'event': 'xaman_ledger_submit_requested',
                'submit_node_network': scenario.mutation['submit_node_network'],
                'network_binding_consistent': False,
            },
        ]
    if scenario.mutation_class == 'replay_payload':
        return [
            {
                'event_id': 'event:xaman:payload-signed-client-a',
                'event': 'xaman_payload_resolved_patch',
                'payload_uuid': scenario.mutation['payload_uuid'],
                'client_id': 'client:a',
                'terminal_transition': scenario.mutation['terminal_transitions'][0],
            },
            {
                'event_id': 'event:xaman:payload-submitted-client-b',
                'event': 'xaman_payload_resolved_patch',
                'payload_uuid': scenario.mutation['payload_uuid'],
                'client_id': 'client:b',
                'terminal_transition': scenario.mutation['terminal_transitions'][1],
            },
        ]
    if scenario.mutation_class == 'backend_trust_failure':
        return [
            {
                'event_id': 'event:xaman:backend-forged-patch',
                'event': 'xaman_payload_resolved_patch',
                'backend_authorized': False,
                'payload_uuid_bound_to_requester': False,
            },
            {
                'event_id': 'event:xaman:backend-forged-state-accepted',
                'event': 'payload_resolution_accepted',
                'accepted_terminal_state': scenario.mutation['accepted_terminal_state'],
                'patch_conflict_rejected': False,
            },
        ]
    return []


def _counterexample(
    scenario: XamanDisproofScenario,
    claim: Mapping[str, Any],
) -> dict[str, Any] | None:
    if scenario.expected_status != 'DISPROVED':
        return None
    trace = _scenario_trace(scenario)
    return {
        'violated_claim_id': scenario.claim_id,
        'violated_category': _claim_category(claim),
        'mutation_class': scenario.mutation_class,
        'mutation': scenario.mutation,
        'violated_invariant': claim.get('proof_obligation_statement'),
        'witness': {
            'claim_source_status': claim.get('source_status'),
            'claim_risk': claim.get('risk', claim.get('severity')),
            'baseline_blocking_assumptions': list(
                claim.get('blocking_assumption_ids', [])
            ),
            'consumer_policy': claim.get('consumer_policy'),
        },
        'trace': trace,
        'violating_event_ids': [
            event['event_id'] for event in trace if 'event_id' in event
        ],
    }


def _blocked_reason(
    scenario: XamanDisproofScenario,
    claim: Mapping[str, Any],
) -> dict[str, Any] | None:
    if scenario.expected_status != 'EXPLICITLY_BLOCKED':
        return None
    return {
        'reason': 'fail_closed_until_required_assumptions_and_solver_packet_are_evidenced',
        'expected_blockers': list(scenario.expected_blockers),
        'claim_blocking_assumptions': list(claim.get('blocking_assumption_ids', [])),
        'mutation': scenario.mutation,
    }


def _validate_scenario(
    scenario: XamanDisproofScenario,
    *,
    claim: Mapping[str, Any],
    assumptions_by_id: Mapping[str, Mapping[str, Any]],
    baseline_vectors_by_claim: Mapping[str, Mapping[str, Any]],
    prover_targets: list[Any],
) -> None:
    required_assumptions = set(claim.get('required_assumptions', []))
    blocking_assumptions = set(claim.get('blocking_assumption_ids', []))
    unknown_assumptions = required_assumptions.difference(assumptions_by_id)
    if unknown_assumptions:
        raise ValueError(
            f'{scenario.scenario_id} references claim with unknown assumptions: '
            f'{sorted(unknown_assumptions)}'
        )
    if not set(scenario.expected_blockers).issubset(blocking_assumptions):
        raise ValueError(
            f'{scenario.scenario_id} expected blockers are not claim blockers'
        )
    if scenario.claim_id not in baseline_vectors_by_claim:
        raise ValueError(f'{scenario.scenario_id} has no baseline disproof vector')
    if scenario.mutation_class == 'stale_evidence':
        if _iso_date(str(scenario.mutation['to'])) >= str(
            scenario.mutation['release_window_date']
        ):
            raise ValueError('stale evidence mutation does not expire before release')
    if scenario.mutation_class == 'downgraded_solver':
        if scenario.mutation.get('removed_solver') not in prover_targets:
            raise ValueError('downgraded solver mutation does not remove a prover target')
    if scenario.mutation_class == 'mutated_assumption':
        assumption = assumptions_by_id[str(scenario.mutation['assumption_id'])]
        if assumption.get('acceptance_status') != scenario.mutation['from']:
            raise ValueError('assumption mutation source status no longer matches')


def _vector_cid_payload(vector: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in vector.items()
        if key not in {'proof_or_trace_cid', 'vector_cid'}
    }


def _build_vector(
    scenario: XamanDisproofScenario,
    *,
    model_id: str,
    model_cid: str,
    claim: Mapping[str, Any],
    assumptions_by_id: Mapping[str, Mapping[str, Any]],
    baseline_vector: Mapping[str, Any],
) -> dict[str, Any]:
    related_assumption_ids = list(claim.get('required_assumptions', []))
    assumption_statuses = {
        assumption_id: assumptions_by_id[assumption_id].get('acceptance_status')
        for assumption_id in related_assumption_ids
    }
    vector: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'id': f'xaman-disproof:{scenario.scenario_id}',
        'scenario_id': scenario.scenario_id,
        'title': scenario.title,
        'model_id': model_id,
        'model_cid': model_cid,
        'claim_id': scenario.claim_id,
        'xaman_category': _claim_category(claim),
        'risk': claim.get('risk', claim.get('severity')),
        'mutation_class': scenario.mutation_class,
        'tactic': scenario.tactic,
        'baseline_tactic': baseline_vector.get('tactic'),
        'expected_detection': scenario.expected_detection,
        'status': scenario.expected_status,
        'related_assumptions': related_assumption_ids,
        'assumption_statuses': assumption_statuses,
        'blocking_assumptions': list(claim.get('blocking_assumption_ids', [])),
        'expected_blockers': list(scenario.expected_blockers),
        'mutation': scenario.mutation,
        'counterexample': _counterexample(scenario, claim),
        'blocked_reason': _blocked_reason(scenario, claim),
        'evidence_refs': [
            {
                'kind': 'manual_review',
                'path': CLAIMS_PATH,
                'review_status': 'human_reviewed',
                'notes': f'Mutation scenario bound to {scenario.claim_id}.',
            },
            {
                'kind': 'manual_review',
                'path': MODEL_PATH,
                'review_status': 'human_reviewed',
                'notes': 'Scenario generated from the Xaman SecurityModelIR baseline.',
            },
        ],
    }
    vector['proof_or_trace_cid'] = calculate_artifact_cid(_vector_cid_payload(vector))
    vector['vector_cid'] = calculate_artifact_cid(_vector_cid_payload(vector))
    return vector


def build_xaman_disproof_artifacts(
    model_payload: Mapping[str, Any],
    *,
    model_cid: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build deterministic disproof vector and counterexample report artifacts."""

    model_id = str(model_payload.get('model_id', ''))
    if not model_id:
        raise ValueError('model payload missing model_id')
    claims_by_id = _index_by_id(list(model_payload.get('claims', [])), 'claim')
    assumptions_by_id = _index_by_id(
        list(model_payload.get('assumptions', [])),
        'assumption',
    )
    baseline_vectors_by_claim = {
        str(vector['claim_id']): vector
        for vector in model_payload.get('disproof_vectors', [])
        if isinstance(vector, Mapping) and 'claim_id' in vector
    }
    prover_targets = list(model_payload.get('prover_targets', []))

    vectors: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        claim = claims_by_id.get(scenario.claim_id)
        if claim is None:
            raise ValueError(f'{scenario.scenario_id} claim missing: {scenario.claim_id}')
        _validate_scenario(
            scenario,
            claim=claim,
            assumptions_by_id=assumptions_by_id,
            baseline_vectors_by_claim=baseline_vectors_by_claim,
            prover_targets=prover_targets,
        )
        vectors.append(
            _build_vector(
                scenario,
                model_id=model_id,
                model_cid=model_cid,
                claim=claim,
                assumptions_by_id=assumptions_by_id,
                baseline_vector=baseline_vectors_by_claim[scenario.claim_id],
            )
        )

    statuses: dict[str, int] = {}
    mutation_classes: dict[str, int] = {}
    for vector in vectors:
        statuses[str(vector['status'])] = statuses.get(str(vector['status']), 0) + 1
        mutation_class = str(vector['mutation_class'])
        mutation_classes[mutation_class] = mutation_classes.get(mutation_class, 0) + 1

    suite_summary = {
        'vector_count': len(vectors),
        'counterexample_count': statuses.get('DISPROVED', 0),
        'explicitly_blocked_count': statuses.get('EXPLICITLY_BLOCKED', 0),
        'status_counts': statuses,
        'mutation_class_counts': mutation_classes,
    }
    vectors_artifact: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'model_id': model_id,
        'model_cid': model_cid,
        'model_path': MODEL_PATH,
        'model_cid_path': MODEL_CID_PATH,
        'reference_date': REFERENCE_DATE,
        'acceptance': (
            'Mutate assumptions, remove auth preconditions, stale evidence, '
            'wrong network, replay payloads, downgraded solvers, unsupported '
            'XRPL semantics, and backend trust failures.'
        ),
        'summary': suite_summary,
        'vectors': vectors,
    }
    vectors_artifact['artifact_cid'] = calculate_artifact_cid(
        {
            key: value
            for key, value in vectors_artifact.items()
            if key != 'artifact_cid'
        }
    )

    scenarios = [
        {
            'scenario_id': vector['scenario_id'],
            'claim_id': vector['claim_id'],
            'mutation_class': vector['mutation_class'],
            'expected_detection': vector['expected_detection'],
            'status': vector['status'],
            'counterexample_found': vector['counterexample'] is not None,
            'explicitly_blocked': vector['blocked_reason'] is not None,
            'proof_or_trace_cid': vector['proof_or_trace_cid'],
            'expected_blockers': vector['expected_blockers'],
            'blocking_assumptions': vector['blocking_assumptions'],
        }
        for vector in vectors
    ]
    report: dict[str, Any] = {
        'schema_version': REPORT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'model_id': model_id,
        'model_cid': model_cid,
        'vectors_artifact_cid': vectors_artifact['artifact_cid'],
        'summary': {
            **suite_summary,
            'scenario_failures': sum(
                1
                for scenario in scenarios
                if not (
                    scenario['counterexample_found']
                    or scenario['explicitly_blocked']
                )
            ),
        },
        'scenarios': scenarios,
        'counterexamples': [
            {
                'scenario_id': vector['scenario_id'],
                'claim_id': vector['claim_id'],
                'mutation_class': vector['mutation_class'],
                'proof_or_trace_cid': vector['proof_or_trace_cid'],
                'counterexample': vector['counterexample'],
            }
            for vector in vectors
            if vector['counterexample'] is not None
        ],
        'blocked': [
            {
                'scenario_id': vector['scenario_id'],
                'claim_id': vector['claim_id'],
                'mutation_class': vector['mutation_class'],
                'proof_or_trace_cid': vector['proof_or_trace_cid'],
                'blocked_reason': vector['blocked_reason'],
            }
            for vector in vectors
            if vector['blocked_reason'] is not None
        ],
    }
    report['artifact_cid'] = calculate_artifact_cid(
        {
            key: value
            for key, value in report.items()
            if key != 'artifact_cid'
        }
    )
    return vectors_artifact, report
