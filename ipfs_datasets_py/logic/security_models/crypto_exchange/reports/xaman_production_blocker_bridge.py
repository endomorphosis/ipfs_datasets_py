"""Bridge Xaman assurance artifacts into production blocker removal.

This report does not remove a blocker.  It classifies what the reviewed
Xaman source-corpus packet can support, separates that evidence from missing
deployed-app evidence, and maps each open packet blocker to the production
evidence domains required before a later task may close it.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid
from .xaman_assurance_packet import FAIL_CLOSED_DECISION

SCHEMA_VERSION = 'xaman-production-blocker-bridge/v1'
TASK_ID = 'PORTAL-CXTP-076'
FIXED_GENERATED_AT_UTC = '2026-07-08T22:30:00Z'

ASSURANCE_PACKET_PATH = 'security_ir_artifacts/corpora/xaman-app/assurance-packet.json'
BRIDGE_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json'
BRIDGE_DOC_PATH = 'docs/security_verification/xaman_to_production_blocker_bridge.md'
PRODUCTION_EVIDENCE_INTAKE_DOC_PATH = 'docs/security_verification/production_evidence_intake.md'
PRODUCTION_ENVIRONMENT_PROFILE_DOC_PATH = 'docs/security_verification/production_environment_profile.md'
VALIDATION_COMMAND = (
    'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest '
    'tests/logic/security_models/crypto_exchange/test_xaman_production_blocker_bridge.py -q'
)

PRODUCTION_EVIDENCE_DOMAINS = (
    'production_source',
    'production_build',
    'production_runtime',
    'production_environment',
    'human_review',
)

DOMAIN_DESCRIPTIONS = {
    'production_source': (
        'Reviewed production source, dependency, native module, backend, policy, '
        'or vendor evidence for the exact release boundary.'
    ),
    'production_build': (
        'Reproducible-build, signed-binary, deployment digest, CI/CD attestation, '
        'or binary-to-source provenance for the release artifact.'
    ),
    'production_runtime': (
        'Release-window runtime traces, real-device traces, integration tests, '
        'or ledger/backend execution traces bound to the deployed build.'
    ),
    'production_environment': (
        'Production environment, custody, solver, node, platform, backend, '
        'or operational configuration evidence.'
    ),
    'human_review': (
        'Named owner or security review accepting the evidence, freshness, '
        'scope, and residual risk for the blocker.'
    ),
}

SOURCE_CORPUS_EVIDENCE_TYPES = (
    'source_manifest',
    'source_coverage',
    'security_claims',
    'security_model',
    'proof_reports',
    'disproof_reports',
    'source_or_e2e_runtime_monitors',
    'proof_consumer_fixture',
)

DEPLOYED_APP_EVIDENCE_TYPES = (
    'production_source_inventory',
    'production_build_provenance',
    'release_window_real_device_traces',
    'production_environment_profile',
    'production_owner_signoff',
)


BLOCKER_DOMAIN_OVERRIDES = {
    'blocker:assumption:xaman-security-assumption-native-vault-cryptographic-confidentiality': (
        'production_source',
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-passcode-kdf-and-secret-protection': (
        'production_source',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-biometric-native-binding': (
        'production_source',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-third-party-signing-correctness': (
        'production_source',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-backend-payload-api-single-use-and-authorization': (
        'production_source',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-intake-decoder-and-os-delivery-integrity': (
        'production_source',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-deployed-network-and-node-config-equivalence': (
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-trustset-and-signerlist-client-validation': (
        'production_source',
        'production_runtime',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-xrpl-server-rule-enforcement-and-consensus': (
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-external-multisign-coordination': (
        'production_source',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-deployed-runtime-equivalence': (
        'production_source',
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:assumption:xaman-security-assumption-proof-receipt-cid-or-signature-validation': (
        'production_source',
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:proof:no-critical-claim-proved': (
        'production_source',
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
    'blocker:solver:apalache': (
        'production_environment',
        'human_review',
    ),
    'blocker:solver:proverif': (
        'production_environment',
        'human_review',
    ),
    'blocker:solver:tamarin-prover': (
        'production_environment',
        'human_review',
    ),
    'blocker:runtime:real-device-traces-absent': (
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ),
}


def _bridge_cid(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid(
        {
            key: value
            for key, value in payload.items()
            if key != 'artifact_cid'
        }
    )


def _assurance_packet_cid(packet: Mapping[str, Any]) -> str:
    value = packet.get('artifact_cid')
    if isinstance(value, str) and value:
        return value
    return _bridge_cid(packet)


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def _domain_requirements(
    blocker: Mapping[str, Any],
    domains: Sequence[str],
) -> list[dict[str, Any]]:
    raw_requirements = list(blocker.get('required_evidence_to_close', []))
    return [
        {
            'domain': domain,
            'status': 'missing',
            'description': DOMAIN_DESCRIPTIONS[domain],
            'source_packet_requirements': deepcopy(raw_requirements),
        }
        for domain in domains
    ]


def _domains_for_blocker(blocker: Mapping[str, Any]) -> tuple[str, ...]:
    blocker_id = str(blocker['id'])
    if blocker_id in BLOCKER_DOMAIN_OVERRIDES:
        return BLOCKER_DOMAIN_OVERRIDES[blocker_id]

    domains = {'human_review'}
    text = ' '.join(
        str(value)
        for value in (
            blocker.get('type'),
            blocker.get('category'),
            blocker.get('reason'),
            ' '.join(map(str, blocker.get('required_evidence_to_close', []))),
        )
    ).lower()
    if any(word in text for word in ('source', 'implementation', 'library', 'sdk', 'backend')):
        domains.add('production_source')
    if any(word in text for word in ('binary', 'build', 'deployment', 'digest', 'provenance')):
        domains.add('production_build')
    if any(word in text for word in ('runtime', 'trace', 'test', 'real-device')):
        domains.add('production_runtime')
    if any(
        word in text
        for word in ('environment', 'node', 'solver', 'keystore', 'keychain', 'configuration')
    ):
        domains.add('production_environment')
    if domains == {'human_review'}:
        domains.update(PRODUCTION_EVIDENCE_DOMAINS[:-1])
    return tuple(domain for domain in PRODUCTION_EVIDENCE_DOMAINS if domain in domains)


def _source_corpus_evidence(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = packet['source']
    runtime = packet['runtime_traces']
    proof_reports = packet['proof_reports']
    disproof_reports = packet['disproof_reports']
    return [
        {
            'id': 'source-corpus:pinned-source-manifest',
            'evidence_type': 'source_manifest',
            'scope': 'source_corpus',
            'status': 'reviewed',
            'path': source['manifest']['path'],
            'artifact_cid': source['manifest']['artifact_cid'],
            'commit_sha': source['commit_sha'],
            'aggregate_sha256': source['manifest']['aggregate_sha256'],
            'production_blocker_effect': 'context-only-does-not-close-production-blockers',
        },
        {
            'id': 'source-corpus:source-coverage',
            'evidence_type': 'source_coverage',
            'scope': 'source_corpus',
            'status': 'reviewed',
            'path': source['coverage']['path'],
            'artifact_cid': source['coverage']['artifact_cid'],
            'coverage_summary': deepcopy(source['coverage']['coverage_summary']),
            'production_blocker_effect': 'context-only-does-not-close-production-blockers',
        },
        {
            'id': 'source-corpus:security-claims-and-assumptions',
            'evidence_type': 'security_claims',
            'scope': 'source_corpus',
            'status': 'partially-evidenced',
            'path': packet['assumptions']['path'],
            'evidenced_assumption_ids': deepcopy(packet['assumptions']['evidenced_assumption_ids']),
            'blocking_assumption_ids': deepcopy(packet['assumptions']['blocking_assumption_ids']),
            'production_blocker_effect': 'records-open-blockers-does-not-close-them',
        },
        {
            'id': 'source-corpus:security-model-ir',
            'evidence_type': 'security_model',
            'scope': 'source_corpus',
            'status': 'modeled',
            'path': packet['model']['path'],
            'model_cid': packet['model']['model_cid'],
            'claim_count': packet['model']['claim_count'],
            'assumption_count': packet['model']['assumption_count'],
            'production_blocker_effect': 'model-input-only',
        },
        {
            'id': 'source-corpus:proof-reports',
            'evidence_type': 'proof_reports',
            'scope': 'source_corpus',
            'status': 'blocked',
            'paths': [report['path'] for report in proof_reports],
            'release_effects': {
                report['id']: report['release_effect']
                for report in proof_reports
            },
            'production_blocker_effect': 'no-critical-claim-proved',
        },
        {
            'id': 'source-corpus:disproof-reports',
            'evidence_type': 'disproof_reports',
            'scope': 'source_corpus',
            'status': 'archived',
            'paths': [report['path'] for report in disproof_reports],
            'release_effects': {
                report['id']: report['release_effect']
                for report in disproof_reports
            },
            'production_blocker_effect': 'negative-fixtures-preserved',
        },
        {
            'id': 'source-corpus:source-and-e2e-runtime-monitors',
            'evidence_type': 'source_or_e2e_runtime_monitors',
            'scope': 'source_corpus',
            'status': 'not-deployed-runtime-equivalent',
            'path': runtime['path'],
            'artifact_cid': runtime['artifact_cid'],
            'monitor_fact_count': runtime['monitor_fact_count'],
            'e2e_feature_count': runtime['trace_inputs']['e2e_feature_count'],
            'real_device_trace_count': runtime['trace_inputs']['real_device_trace_count'],
            'production_blocker_effect': 'real-device-runtime-equivalence-still-missing',
        },
        {
            'id': 'source-corpus:proof-consumer-fixture',
            'evidence_type': 'proof_consumer_fixture',
            'scope': 'source_corpus',
            'status': 'fixture-accepted',
            'path': next(
                report['path']
                for report in proof_reports
                if report['id'] == 'xaman-proof-consumer-invariants'
            ),
            'production_blocker_effect': 'policy-fixture-only-production-validation-still-missing',
        },
    ]


def _deployed_app_evidence(packet: Mapping[str, Any]) -> dict[str, Any]:
    runtime = packet['runtime_traces']
    return {
        'scope': 'deployed_app',
        'status': 'absent',
        'accepted_evidence_count': 0,
        'accepted_evidence': [],
        'real_device_trace_count': runtime['trace_inputs']['real_device_trace_count'],
        'production_release_ready': False,
        'missing_evidence': [
            {
                'evidence_type': evidence_type,
                'domain': domain,
                'status': 'missing',
                'required_before_blocker_removal': True,
            }
            for evidence_type, domain in zip(
                DEPLOYED_APP_EVIDENCE_TYPES,
                PRODUCTION_EVIDENCE_DOMAINS,
            )
        ],
    }


def _map_blocker(blocker: Mapping[str, Any]) -> dict[str, Any]:
    domains = _domains_for_blocker(blocker)
    return {
        'id': f'bridge:{_slug(str(blocker["id"]))}',
        'source_packet_blocker_id': blocker['id'],
        'type': blocker['type'],
        'category': blocker.get('category') or blocker.get('solver') or blocker['type'],
        'severity': blocker['severity'],
        'release_effect': blocker['release_effect'],
        'removal_status': 'blocked_missing_production_evidence',
        'source_corpus_evidence_status': 'mapped-but-insufficient-for-production',
        'deployed_app_evidence_status': 'missing',
        'blocked_claim_ids': deepcopy(blocker.get('blocked_claim_ids', [])),
        'reason': blocker['reason'],
        'required_evidence_to_close_from_packet': deepcopy(
            blocker.get('required_evidence_to_close', [])
        ),
        'required_production_evidence_domains': list(domains),
        'domain_requirements': _domain_requirements(blocker, domains),
    }


def _blockers_by_domain(blocker_mappings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_domain: dict[str, list[str]] = {
        domain: []
        for domain in PRODUCTION_EVIDENCE_DOMAINS
    }
    for mapping in blocker_mappings:
        for domain in mapping['required_production_evidence_domains']:
            by_domain[domain].append(mapping['source_packet_blocker_id'])
    return {
        domain: {
            'blocker_count': len(blocker_ids),
            'blocker_ids': blocker_ids,
            'status': 'missing',
            'description': DOMAIN_DESCRIPTIONS[domain],
        }
        for domain, blocker_ids in by_domain.items()
    }


def _claim_blocker_map(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers_by_claim: dict[str, list[str]] = {}
    for blocker in packet['open_blockers']:
        for claim_id in blocker.get('blocked_claim_ids', []):
            blockers_by_claim.setdefault(claim_id, []).append(blocker['id'])

    return [
        {
            'claim_id': decision['claim_id'],
            'release_gate': decision['release_gate'],
            'consumer_outcome': decision['consumer_outcome'],
            'secure_for_release': decision['secure_for_release'],
            'source_status': decision['source_status'],
            'blocked_by_packet_blocker_ids': sorted(
                blockers_by_claim.get(decision['claim_id'], [])
            ),
            'remaining_production_blocker_count': len(
                blockers_by_claim.get(decision['claim_id'], [])
            ),
        }
        for decision in packet['claim_decisions']
    ]


def build_xaman_production_blocker_bridge(
    assurance_packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic production-blocker bridge from the assurance packet."""

    source_evidence = _source_corpus_evidence(assurance_packet)
    deployed_evidence = _deployed_app_evidence(assurance_packet)
    blocker_mappings = [
        _map_blocker(blocker)
        for blocker in assurance_packet['open_blockers']
    ]
    blockers_by_domain = _blockers_by_domain(blocker_mappings)
    bridge = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': FIXED_GENERATED_AT_UTC,
        'corpus': assurance_packet['corpus'],
        'source_packet': {
            'path': ASSURANCE_PACKET_PATH,
            'schema_version': assurance_packet['schema_version'],
            'task_id': assurance_packet['task_id'],
            'artifact_cid': _assurance_packet_cid(assurance_packet),
            'model_cid': assurance_packet['model']['model_cid'],
            'commit_sha': assurance_packet['source']['commit_sha'],
            'release_decision': assurance_packet['release_decision']['decision'],
            'open_blocker_count': assurance_packet['release_decision']['open_blocker_count'],
        },
        'production_evidence_domains': [
            {
                'domain': domain,
                'description': DOMAIN_DESCRIPTIONS[domain],
                'status': 'missing',
            }
            for domain in PRODUCTION_EVIDENCE_DOMAINS
        ],
        'evidence_scope': {
            'source_corpus': {
                'scope': 'source_corpus',
                'status': 'available_for_review_context',
                'accepted_for_deployed_app_release': False,
                'evidence_types': list(SOURCE_CORPUS_EVIDENCE_TYPES),
                'evidence_count': len(source_evidence),
                'evidence': source_evidence,
            },
            'deployed_app': deployed_evidence,
        },
        'claim_blocker_map': _claim_blocker_map(assurance_packet),
        'blocker_mappings': blocker_mappings,
        'remaining_blockers_by_domain': blockers_by_domain,
        'production_blocker_removal_policy': {
            'decision': FAIL_CLOSED_DECISION,
            'may_remove_any_blocker': False,
            'required_before_removal': [
                'Every mapped blocker has current evidence for each listed production evidence domain.',
                'Deployed-app evidence is separated from source-corpus evidence and reviewed independently.',
                'Every blocking/high claim has an accepted PROVED outcome bound to the release packet.',
                'Human owners accept freshness, scope, and residual risk for each blocker removal.',
            ],
            'production_evidence_intake_doc': PRODUCTION_EVIDENCE_INTAKE_DOC_PATH,
            'production_environment_profile_doc': PRODUCTION_ENVIRONMENT_PROFILE_DOC_PATH,
        },
        'summary': {
            'source_corpus_evidence_count': len(source_evidence),
            'deployed_app_accepted_evidence_count': deployed_evidence['accepted_evidence_count'],
            'open_blocker_count': len(blocker_mappings),
            'source_packet_open_blocker_count': assurance_packet['release_decision'][
                'open_blocker_count'
            ],
            'remaining_domain_count': len(PRODUCTION_EVIDENCE_DOMAINS),
            'domain_blocker_counts': {
                domain: detail['blocker_count']
                for domain, detail in blockers_by_domain.items()
            },
            'decision': FAIL_CLOSED_DECISION,
            'release_ready': False,
        },
        'validation': {
            'command': VALIDATION_COMMAND,
            'test_path': (
                'tests/logic/security_models/crypto_exchange/'
                'test_xaman_production_blocker_bridge.py'
            ),
        },
        'document_path': BRIDGE_DOC_PATH,
    }
    bridge['artifact_cid'] = _bridge_cid(bridge)
    return bridge
