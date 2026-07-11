"""Deterministic Xaman Testnet trace and input-space fuzz campaigns."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Callable, Mapping

from ..ir.cid import calculate_artifact_cid
from ..ir.schema import SecurityModelIR, validate_ir


SCHEMA_VERSION = 'xaman-testnet-fuzz-report/v1'
TASK_ID = 'PORTAL-CXTP-138'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid'
TRACE_MAP_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json'
FUZZ_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json'
COUNTEREXAMPLE_DIR = 'security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples'

EXPECTED_ACTIONS = (
    'payload_intake',
    'review',
    'auth_decision',
    'signing_decision',
    'submit_attempt',
    'submit_result',
    'reconnect',
    'network_switch',
)
EXPECTED_COVERAGE_GAPS = frozenset({'decline', 'cancel', 'expiry'})
EXPECTED_EVENT_FIELDS = {
    'payload_intake': {'category': 'payload_intake', 'outcome': 'accepted'},
    'review': {'category': 'payload_review', 'outcome': 'reviewed'},
    'auth_decision': {'category': 'auth_decision', 'outcome': 'authorized'},
    'signing_decision': {'category': 'signing_decision', 'outcome': 'signed'},
    'submit_attempt': {'category': 'submit_attempt', 'outcome': 'submitted'},
    'submit_result': {'category': 'submit_result', 'outcome': 'succeeded'},
    'reconnect': {'category': 'reconnect', 'outcome': 'reconnected'},
    'network_switch': {'category': 'network_switch', 'outcome': 'switched_to_testnet'},
}

CLAIMS = {
    'network': 'xaman-testnet-claim:network-binding-is-testnet-only',
    'account': 'xaman-testnet-claim:account-provenance-is-fresh-testnet-only',
    'review_auth': 'xaman-testnet-claim:review-auth-sequence-observed',
    'signing': 'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
    'submission': 'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
    'payload': 'xaman-testnet-claim:payload-intake-is-categorical-only',
    'refusal': 'xaman-testnet-claim:refusal-path-is-not-modeled',
    'replay': 'xaman-testnet-claim:replay-controls-are-not-modeled',
    'expiry': 'xaman-testnet-claim:expiry-path-is-not-modeled',
    'cancellation': 'xaman-testnet-claim:cancellation-path-is-not-modeled',
    'broadcast': 'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
    'redaction': 'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
}

SENSITIVE_KEY_FRAGMENTS = (
    'account_address',
    'classic_address',
    'credential',
    'mnemonic',
    'passcode',
    'password',
    'payload_json',
    'private_key',
    'raw_payload',
    'request_body',
    'response_body',
    'secret',
    'seed',
    'signature',
    'signed_transaction_blob',
    'transaction_blob',
)
XRPL_CLASSIC_ADDRESS_RE = re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{25,35}\b')
XRPL_FAMILY_SEED_RE = re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b')


class FuzzRejection(ValueError):
    """Expected fail-closed rejection raised by a campaign oracle."""


@dataclass(frozen=True, slots=True)
class CampaignCase:
    case_id: str
    title: str
    expected: str
    target_claim_id: str | None
    payload: dict[str, Any]
    oracle: Callable[[dict[str, Any], Mapping[str, Any]], list[str]]


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _artifact_cid_without_self(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _redaction_breaches(value: Any, *, path: str = '$') -> list[str]:
    breaches: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = f'{path}.{key_text}'
            normalized_key = key_text.lower()
            if any(fragment in normalized_key for fragment in SENSITIVE_KEY_FRAGMENTS):
                if item not in (None, False, '', [], {}):
                    breaches.append(f'{path}.<sensitive-redacted-field>')
            breaches.extend(_redaction_breaches(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            breaches.extend(_redaction_breaches(item, path=f'{path}[{index}]'))
    elif isinstance(value, str):
        if XRPL_CLASSIC_ADDRESS_RE.search(value) or XRPL_FAMILY_SEED_RE.search(value):
            breaches.append(path)
    return breaches


def assert_no_redaction_breach(payload: Mapping[str, Any]) -> None:
    breaches = _redaction_breaches(payload)
    if breaches:
        raise FuzzRejection(f'redaction breach rejected at {", ".join(sorted(breaches))}')


def _seed_trace(model_payload: Mapping[str, Any]) -> dict[str, Any]:
    events = sorted(
        (
            event
            for event in model_payload.get('events', [])
            if isinstance(event, Mapping) and event.get('testnet_action') in EXPECTED_ACTIONS
        ),
        key=lambda event: int(event.get('ordinal', 0)),
    )
    return {
        'network_key': 'TESTNET',
        'network_id': 1,
        'fresh_account_boundary': {
            'fresh_account_created': True,
            'imported_account': False,
            'production_account': False,
            'account_material_recorded': False,
        },
        'coverage_gaps': [
            {'action': 'decline', 'reason_code': 'not_exercised_in_reviewed_trial'},
            {'action': 'cancel', 'reason_code': 'not_exercised_in_reviewed_trial'},
            {'action': 'expiry', 'reason_code': 'not_exercised_in_reviewed_trial'},
        ],
        'events': [
            {
                'ordinal': event['ordinal'],
                'action': event['testnet_action'],
                'category': event['category'],
                'outcome': event['outcome'],
                'source_kind': event['source_kind'],
                'raw_material_recorded': event['raw_material_recorded'],
                'redaction_sha256': event['redaction_sha256'],
            }
            for event in events
        ],
    }


def validate_trace_input(payload: Mapping[str, Any], _model_payload: Mapping[str, Any]) -> list[str]:
    assert_no_redaction_breach(payload)
    if payload.get('network_key') != 'TESTNET' or payload.get('network_id') != 1:
        raise FuzzRejection('network binding must remain XRPL Testnet key TESTNET with network_id 1')
    account = payload.get('fresh_account_boundary')
    if not isinstance(account, Mapping):
        raise FuzzRejection('fresh account boundary missing')
    if account.get('fresh_account_created') is not True:
        raise FuzzRejection('fresh Testnet account creation was not observed')
    if account.get('imported_account') is not False or account.get('production_account') is not False:
        raise FuzzRejection('imported or production account boundary rejected')
    if account.get('account_material_recorded') is not False:
        raise FuzzRejection('account material retention rejected')

    gaps = payload.get('coverage_gaps')
    if not isinstance(gaps, list):
        raise FuzzRejection('coverage_gaps must be a list')
    gap_actions = {gap.get('action') for gap in gaps if isinstance(gap, Mapping)}
    if gap_actions != EXPECTED_COVERAGE_GAPS:
        raise FuzzRejection('coverage gaps must remain exactly decline, cancel, and expiry')
    for gap in gaps:
        if not isinstance(gap, Mapping) or gap.get('reason_code') != 'not_exercised_in_reviewed_trial':
            raise FuzzRejection('coverage gap reason must remain not_exercised_in_reviewed_trial')

    events = payload.get('events')
    if not isinstance(events, list):
        raise FuzzRejection('events must be a list')
    if len(events) != len(EXPECTED_ACTIONS):
        raise FuzzRejection('trace event count changed')
    seen_actions: set[str] = set()
    seen_ordinals: set[int] = set()
    for event in events:
        if not isinstance(event, Mapping):
            raise FuzzRejection('trace event must be a mapping')
        action = event.get('action')
        ordinal = event.get('ordinal')
        if action not in EXPECTED_ACTIONS:
            raise FuzzRejection(f'unrecognized trace action: {action!r}')
        if action in seen_actions:
            raise FuzzRejection(f'duplicate trace action: {action}')
        if not isinstance(ordinal, int) or ordinal < 1:
            raise FuzzRejection(f'invalid ordinal for action {action}')
        if ordinal in seen_ordinals:
            raise FuzzRejection(f'duplicate trace ordinal: {ordinal}')
        if event.get('source_kind') != 'reviewed_ui':
            raise FuzzRejection(f'action {action} is not reviewed UI evidence')
        if event.get('raw_material_recorded') is not False:
            raise FuzzRejection(f'action {action} retained raw material')
        expected = EXPECTED_EVENT_FIELDS[str(action)]
        if event.get('category') != expected['category'] or event.get('outcome') != expected['outcome']:
            raise FuzzRejection(f'action {action} category or outcome changed')
        seen_actions.add(str(action))
        seen_ordinals.add(int(ordinal))
    if tuple(event['action'] for event in events) != EXPECTED_ACTIONS:
        raise FuzzRejection('trace event order changed')
    if tuple(event['ordinal'] for event in events) != tuple(range(1, len(EXPECTED_ACTIONS) + 1)):
        raise FuzzRejection('trace ordinals changed')
    return []


def parse_untrusted_ir(payload: Mapping[str, Any], _model_payload: Mapping[str, Any]) -> list[str]:
    try:
        parsed = SecurityModelIR.from_untrusted_dict(payload, strict=True)
        validate_ir(parsed)
    except ValueError as exc:
        raise FuzzRejection(str(exc)) from exc
    return []


def _claim_ids(model_payload: Mapping[str, Any]) -> set[str]:
    return {
        claim['id']
        for claim in model_payload.get('claims', [])
        if isinstance(claim, Mapping) and isinstance(claim.get('id'), str)
    }


def _triggered_claims(payload: Mapping[str, Any], model_payload: Mapping[str, Any]) -> list[str]:
    assert_no_redaction_breach({'redaction_screened_payload': payload})
    known_claims = _claim_ids(model_payload)
    triggered: set[str] = set()
    mutation = payload.get('mutation')
    if not isinstance(mutation, Mapping):
        raise FuzzRejection('attack mutation payload missing mutation mapping')
    if mutation.get('payload_material_boundary_crossed') is True:
        triggered.add(CLAIMS['payload'])
        triggered.add(CLAIMS['redaction'])
    if mutation.get('signing_material_boundary_crossed') is True:
        triggered.add(CLAIMS['signing'])
        triggered.add(CLAIMS['redaction'])
    if mutation.get('auth_decision_removed') is True or mutation.get('signing_before_auth') is True:
        triggered.add(CLAIMS['review_auth'])
    if mutation.get('network_key') not in (None, 'TESTNET') or mutation.get('network_id') not in (None, 1):
        triggered.add(CLAIMS['network'])
    if mutation.get('imported_account') is True or mutation.get('production_account') is True:
        triggered.add(CLAIMS['account'])
    if mutation.get('duplicate_payload_resolution') is True or mutation.get('duplicate_submit_result') is True:
        triggered.add(CLAIMS['replay'])
    if mutation.get('coverage_gap_promoted') == 'decline':
        triggered.add(CLAIMS['refusal'])
    if mutation.get('coverage_gap_promoted') == 'cancel':
        triggered.add(CLAIMS['cancellation'])
    if mutation.get('coverage_gap_promoted') == 'expiry':
        triggered.add(CLAIMS['expiry'])
    if mutation.get('ledger_finality_or_broadcast_proof_forged') is True:
        triggered.add(CLAIMS['broadcast'])
    if mutation.get('submit_result_removed') is True:
        triggered.add(CLAIMS['submission'])
    unknown = sorted(triggered - known_claims)
    if unknown:
        raise FuzzRejection(f'attack mutation references unknown claim(s): {", ".join(unknown)}')
    return sorted(triggered)


def validate_attack_mutation(payload: Mapping[str, Any], model_payload: Mapping[str, Any]) -> list[str]:
    triggered = _triggered_claims(payload, model_payload)
    target_claim_id = payload.get('target_claim_id')
    if not isinstance(target_claim_id, str) or not target_claim_id:
        raise FuzzRejection('attack mutation missing target claim')
    if target_claim_id not in triggered:
        raise FuzzRejection(f'attack mutation did not trigger target claim {target_claim_id}')
    return triggered


def _trace_cases(seed: Mapping[str, Any]) -> list[CampaignCase]:
    cases: list[CampaignCase] = [
        CampaignCase(
            case_id='trace-seed-reviewed-valid',
            title='Reviewed Testnet lifecycle trace remains accepted',
            expected='accepted',
            target_claim_id=None,
            payload=deepcopy(dict(seed)),
            oracle=validate_trace_input,
        )
    ]

    def add(case_id: str, title: str, target: str, mutate: Callable[[dict[str, Any]], None]) -> None:
        payload = deepcopy(dict(seed))
        mutate(payload)
        cases.append(
            CampaignCase(
                case_id=case_id,
                title=title,
                expected='rejected',
                target_claim_id=target,
                payload=payload,
                oracle=validate_trace_input,
            )
        )

    add(
        'trace-duplicate-action',
        'Duplicate action creates ambiguous reviewed trace mapping',
        CLAIMS['review_auth'],
        lambda payload: payload['events'][1].update({'action': payload['events'][0]['action']}),
    )
    add(
        'trace-duplicate-ordinal',
        'Duplicate ordinal creates ambiguous reviewed trace mapping',
        CLAIMS['review_auth'],
        lambda payload: payload['events'][1].update({'ordinal': payload['events'][0]['ordinal']}),
    )
    add(
        'trace-signing-before-auth',
        'Signing event is reordered before auth decision',
        CLAIMS['review_auth'],
        lambda payload: payload['events'].__setitem__(2, payload['events'].pop(3)),
    )
    add(
        'trace-unreviewed-source-kind',
        'Unreviewed source-derived event tries to enter the model',
        CLAIMS['redaction'],
        lambda payload: payload['events'][0].update({'source_kind': 'heuristic_source_scan'}),
    )
    add(
        'trace-raw-material-recorded',
        'Trace event records raw material flag',
        CLAIMS['redaction'],
        lambda payload: payload['events'][0].update({'raw_material_recorded': True}),
    )
    add(
        'trace-redaction-breach-field',
        'Trace event attempts to retain a sensitive raw payload field',
        CLAIMS['redaction'],
        lambda payload: payload['events'][0].update({'raw_payload_json': True}),
    )
    add(
        'trace-missing-cancel-gap',
        'Cancellation coverage gap is silently dropped',
        CLAIMS['cancellation'],
        lambda payload: payload.update(
            {'coverage_gaps': [gap for gap in payload['coverage_gaps'] if gap['action'] != 'cancel']}
        ),
    )
    add(
        'trace-wrong-network',
        'Trace is rebound away from XRPL Testnet',
        CLAIMS['network'],
        lambda payload: payload.update({'network_key': 'MAINNET', 'network_id': 0}),
    )
    add(
        'trace-imported-production-account',
        'Trace imports a production account boundary',
        CLAIMS['account'],
        lambda payload: payload['fresh_account_boundary'].update({'imported_account': True, 'production_account': True}),
    )
    add(
        'trace-submit-result-outcome-changed',
        'Submit result categorical outcome is changed',
        CLAIMS['submission'],
        lambda payload: payload['events'][5].update({'outcome': 'unknown'}),
    )
    return cases


def _malformed_ir_cases(model_payload: Mapping[str, Any]) -> list[CampaignCase]:
    cases: list[CampaignCase] = [
        CampaignCase(
            case_id='ir-seed-valid',
            title='Reviewed Testnet SecurityModelIR parses as trusted baseline',
            expected='accepted',
            target_claim_id=None,
            payload=deepcopy(dict(model_payload)),
            oracle=parse_untrusted_ir,
        )
    ]

    def add(case_id: str, title: str, mutate: Callable[[dict[str, Any]], None]) -> None:
        payload = deepcopy(dict(model_payload))
        mutate(payload)
        cases.append(
            CampaignCase(
                case_id=case_id,
                title=title,
                expected='rejected',
                target_claim_id=None,
                payload=payload,
                oracle=parse_untrusted_ir,
            )
        )

    add('ir-unknown-top-level', 'Unknown top-level field is rejected', lambda payload: payload.update({'forged': True}))
    add('ir-missing-model-id', 'Missing model_id is rejected', lambda payload: payload.pop('model_id', None))
    add('ir-events-not-list', 'Non-list events field is rejected', lambda payload: payload.update({'events': {}}))
    add('ir-event-entry-not-mapping', 'Non-mapping event entry is rejected', lambda payload: payload['events'].__setitem__(0, 'bad-event'))
    add('ir-duplicate-claim-id', 'Duplicate claim id is rejected', lambda payload: payload['claims'].append(deepcopy(payload['claims'][0])))
    add('ir-unknown-claim-domain', 'Unknown claim domain without custom flag is rejected', lambda payload: payload['claims'][0].update({'domain': 'unknown_domain', 'custom': False}))
    add('ir-invalid-proof-status', 'Invalid proof obligation status is rejected', lambda payload: payload['proof_obligations'][0].update({'status': 'PROVEN_BY_ASSERTION'}))
    add('ir-invalid-solver-result', 'Invalid solver result is rejected', lambda payload: payload['solver_results'][0].update({'result': 'proved'}))
    add('ir-unsupported-prover-target', 'Unsupported prover target is rejected', lambda payload: payload['prover_targets'].append('magic-solver'))
    add('ir-runtime-trace-unknown-event', 'Runtime trace referencing unknown event is rejected', lambda payload: payload['runtime_traces'][0]['events'].append('missing-event'))
    return cases


def _attack_cases() -> list[CampaignCase]:
    specs = [
        (
            'attack-raw-payload-material',
            'Raw payload material is introduced into the payload boundary',
            CLAIMS['payload'],
            {'payload_material_boundary_crossed': True},
        ),
        (
            'attack-raw-signature-blob',
            'Raw signature or transaction blob material is introduced',
            CLAIMS['signing'],
            {'signing_material_boundary_crossed': True},
        ),
        (
            'attack-signing-before-auth',
            'Signing is allowed before auth decision',
            CLAIMS['review_auth'],
            {'signing_before_auth': True, 'auth_decision_removed': True},
        ),
        (
            'attack-wrong-network',
            'Payload is rebound to non-Testnet network metadata',
            CLAIMS['network'],
            {'network_key': 'MAINNET', 'network_id': 0},
        ),
        (
            'attack-imported-production-account',
            'Imported production account provenance is introduced',
            CLAIMS['account'],
            {'imported_account': True, 'production_account': True},
        ),
        (
            'attack-replay-duplicate-resolution',
            'Duplicate payload resolution is accepted',
            CLAIMS['replay'],
            {'duplicate_payload_resolution': True},
        ),
        (
            'attack-decline-gap-promoted',
            'Decline coverage gap is promoted to modeled runtime path',
            CLAIMS['refusal'],
            {'coverage_gap_promoted': 'decline'},
        ),
        (
            'attack-cancel-gap-promoted',
            'Cancellation coverage gap is promoted to modeled runtime path',
            CLAIMS['cancellation'],
            {'coverage_gap_promoted': 'cancel'},
        ),
        (
            'attack-expiry-gap-promoted',
            'Expiry coverage gap is promoted to modeled runtime path',
            CLAIMS['expiry'],
            {'coverage_gap_promoted': 'expiry'},
        ),
        (
            'attack-forged-broadcast-finality',
            'Forged broadcast/finality proof is accepted as modeled evidence',
            CLAIMS['broadcast'],
            {'ledger_finality_or_broadcast_proof_forged': True},
        ),
        (
            'attack-submit-result-removed',
            'Submit result observation is removed from the trace',
            CLAIMS['submission'],
            {'submit_result_removed': True},
        ),
    ]
    return [
        CampaignCase(
            case_id=case_id,
            title=title,
            expected='target_claim_triggered',
            target_claim_id=target,
            payload={
                'mutation_id': case_id,
                'target_claim_id': target,
                'mutation': mutation,
                'raw_material_retained': False,
                'uses_categorical_markers_only': True,
            },
            oracle=validate_attack_mutation,
        )
        for case_id, title, target, mutation in specs
    ]


def _run_case(case: CampaignCase, model_payload: Mapping[str, Any]) -> dict[str, Any]:
    payload_digest = _sha256_json(case.payload)
    try:
        triggered_claims = case.oracle(case.payload, model_payload)
    except FuzzRejection as exc:
        accepted = False
        rejection = str(exc)
        crash = None
        triggered_claims = []
    except Exception as exc:  # pragma: no cover - exercised by injected tests when needed
        accepted = False
        rejection = None
        crash = f'{type(exc).__name__}: {exc}'
        triggered_claims = []
    else:
        accepted = True
        rejection = None
        crash = None

    if case.expected == 'accepted':
        status = 'passed' if accepted and crash is None else 'failed'
    elif case.expected == 'rejected':
        status = 'passed' if not accepted and rejection and crash is None else 'failed'
    elif case.expected == 'target_claim_triggered':
        status = (
            'passed'
            if accepted
            and crash is None
            and isinstance(case.target_claim_id, str)
            and case.target_claim_id in triggered_claims
            else 'failed'
        )
    else:
        status = 'failed'

    result = 'accepted' if accepted else 'rejected'
    if case.expected == 'target_claim_triggered' and status == 'passed':
        result = 'target_claim_triggered'
    if crash:
        result = 'fuzzer_crash'

    return {
        'case_id': case.case_id,
        'title': case.title,
        'expected': case.expected,
        'result': result,
        'status': status,
        'target_claim_id': case.target_claim_id,
        'triggered_claim_ids': triggered_claims,
        'payload_sha256': payload_digest,
        'rejection_reason': rejection,
        'crash': crash,
    }


def _campaign_summary(campaign_id: str, cases: list[CampaignCase], model_payload: Mapping[str, Any]) -> dict[str, Any]:
    results = [_run_case(case, model_payload) for case in cases]
    return {
        'campaign_id': campaign_id,
        'status': 'passed' if all(result['status'] == 'passed' for result in results) else 'failed',
        'generated_case_count': len(results),
        'accepted_case_count': sum(1 for result in results if result['result'] == 'accepted'),
        'expected_rejection_count': sum(1 for case in cases if case.expected == 'rejected'),
        'actual_rejection_count': sum(1 for result in results if result['result'] == 'rejected'),
        'target_claim_trigger_count': sum(1 for result in results if result['result'] == 'target_claim_triggered'),
        'unexpected_acceptance_count': sum(
            1
            for case, result in zip(cases, results, strict=True)
            if case.expected == 'rejected' and result['result'] == 'accepted'
        ),
        'crash_count': sum(1 for result in results if result['crash']),
        'cases': results,
    }


def counterexample_artifacts(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for mutation in report.get('attack_mutations', []):
        if not isinstance(mutation, Mapping):
            continue
        mutation_id = str(mutation['mutation_id'])
        path = f'{COUNTEREXAMPLE_DIR}/{mutation_id}.json'
        artifact = {
            'schema_version': 'xaman-testnet-fuzz-counterexample/v1',
            'task_id': TASK_ID,
            'mutation_id': mutation_id,
            'target_claim_id': mutation['target_claim_id'],
            'triggered_claim_ids': mutation['triggered_claim_ids'],
            'result': mutation['result'],
            'payload_sha256': mutation['payload_sha256'],
            'raw_sensitive_material_recorded': False,
            'redaction_policy': 'categorical_mutation_markers_only',
            'model_cid': report['model']['cid'],
        }
        artifact['artifact_cid'] = _artifact_cid_without_self(artifact)
        artifacts[path] = artifact
    manifest = {
        'schema_version': 'xaman-testnet-fuzz-counterexample-manifest/v1',
        'task_id': TASK_ID,
        'model_cid': report['model']['cid'],
        'counterexample_count': len(artifacts),
        'counterexamples': sorted(artifacts),
    }
    manifest['artifact_cid'] = _artifact_cid_without_self(manifest)
    artifacts[f'{COUNTEREXAMPLE_DIR}/manifest.json'] = manifest
    return artifacts


def build_xaman_testnet_fuzz_report(
    model_payload: Mapping[str, Any],
    *,
    model_cid: str,
    trace_map_payload: Mapping[str, Any],
) -> dict[str, Any]:
    validate_ir(model_payload)
    expected_claim_ids = set(CLAIMS.values())
    missing_claims = sorted(expected_claim_ids - _claim_ids(model_payload))
    if missing_claims:
        raise ValueError(f'Testnet fuzz campaign missing target claim(s): {", ".join(missing_claims)}')
    if trace_map_payload.get('model_cid') != model_cid:
        raise ValueError('trace map model_cid does not match fuzz model_cid')

    seed = _seed_trace(model_payload)
    campaigns = [
        _campaign_summary('trace-mutation-campaign', _trace_cases(seed), model_payload),
        _campaign_summary('malformed-security-ir-parser-campaign', _malformed_ir_cases(model_payload), model_payload),
        _campaign_summary('expected-attack-mutation-campaign', _attack_cases(), model_payload),
    ]
    attack_case_results = campaigns[-1]['cases']
    attack_mutations = [
        {
            'mutation_id': result['case_id'],
            'title': result['title'],
            'target_claim_id': result['target_claim_id'],
            'triggered_claim_ids': result['triggered_claim_ids'],
            'result': result['result'],
            'status': result['status'],
            'payload_sha256': result['payload_sha256'],
            'counterexample_path': f'{COUNTEREXAMPLE_DIR}/{result["case_id"]}.json',
        }
        for result in attack_case_results
    ]
    malformed_ir_acceptance_count = sum(
        1
        for result in campaigns[1]['cases']
        if result['case_id'] != 'ir-seed-valid' and result['result'] == 'accepted'
    )
    redaction_breach_acceptance_count = sum(
        1
        for result in campaigns[0]['cases'] + campaigns[2]['cases']
        if result['case_id'] in {'trace-raw-material-recorded', 'trace-redaction-breach-field'}
        and result['status'] != 'passed'
    )
    missing_target_claim_trigger_count = sum(
        1
        for mutation in attack_mutations
        if mutation['target_claim_id'] not in mutation['triggered_claim_ids']
    )
    crash_count = sum(campaign['crash_count'] for campaign in campaigns)
    total_cases = sum(campaign['generated_case_count'] for campaign in campaigns)
    failed_case_count = sum(
        1
        for campaign in campaigns
        for result in campaign['cases']
        if result['status'] != 'passed'
    )
    overall_passed = (
        crash_count == 0
        and malformed_ir_acceptance_count == 0
        and redaction_breach_acceptance_count == 0
        and missing_target_claim_trigger_count == 0
        and failed_case_count == 0
    )
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model': {
            'path': MODEL_PATH,
            'cid': model_cid,
            'sha256': _sha256_json(model_payload),
        },
        'trace_map': {
            'path': TRACE_MAP_PATH,
            'artifact_cid': trace_map_payload.get('artifact_cid'),
            'model_cid': trace_map_payload.get('model_cid'),
        },
        'coverage_statement': {
            'scope': 'bounded_generated_testnet_trace_and_input_mutations',
            'not_exhaustive_wallet_input_space': True,
            'description': (
                'The campaign covers deterministic generated mutations over the reviewed XRPL Testnet '
                'trace and selected categorical wallet input classes. It is not a claim over all possible '
                'wallet inputs or production runtime behavior.'
            ),
        },
        'fuzzer': {
            'engine': 'deterministic-structural-mutator',
            'randomness': 'none',
            'campaign_material_sha256': _sha256_json({'model_cid': model_cid, 'task_id': TASK_ID}),
            'total_case_count': total_cases,
        },
        'campaigns': campaigns,
        'attack_mutations': attack_mutations,
        'acceptance_gates': {
            'fuzzer_crash': 'pass' if crash_count == 0 else 'fail',
            'redaction_breach': 'pass' if redaction_breach_acceptance_count == 0 else 'fail',
            'malformed_security_ir_parser': 'pass' if malformed_ir_acceptance_count == 0 else 'fail',
            'expected_attack_mutation_targets': 'pass' if missing_target_claim_trigger_count == 0 else 'fail',
        },
        'summary': {
            'overall_status': 'passed' if overall_passed else 'failed',
            'security_decision': (
                'TESTNET_FUZZ_CAMPAIGNS_PASSED_BOUNDED_GENERATED_COVERAGE'
                if overall_passed
                else 'BLOCK_TESTNET_FUZZ_CAMPAIGN_FAILURE'
            ),
            'total_case_count': total_cases,
            'failed_case_count': failed_case_count,
            'fuzzer_crash_count': crash_count,
            'malformed_ir_acceptance_count': malformed_ir_acceptance_count,
            'redaction_breach_acceptance_count': redaction_breach_acceptance_count,
            'missing_target_claim_trigger_count': missing_target_claim_trigger_count,
            'counterexample_count': len(attack_mutations),
        },
    }
    report['artifact_cid'] = _artifact_cid_without_self(report)
    if not overall_passed:
        raise ValueError('Xaman Testnet fuzz campaign failed acceptance gates')
    return report
