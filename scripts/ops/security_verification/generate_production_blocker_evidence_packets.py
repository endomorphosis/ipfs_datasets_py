#!/usr/bin/env python3
"""Generate evidence request packets for remaining production blockers.

PORTAL-CXTP-094 turns the Xaman source-corpus production-blocker bridge
into concrete production evidence requests.  It does not remove any blocker:
every packet is a checklist of deployed-app evidence that must be collected,
reviewed, and validated by the production evidence bundle validator before a
later guarded updater may propose any status change.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (  # noqa: E402
    calculate_artifact_cid,
)


SCHEMA_VERSION = 'production-blocker-evidence-packets/v1'
TASK_ID = 'PORTAL-CXTP-094'
FIXED_GENERATED_AT_UTC = '2026-07-09T00:00:00Z'
DEFAULT_BRIDGE = Path('security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json')
DEFAULT_SCHEMA = Path('security_ir_artifacts/production/evidence-bundle.schema.json')
DEFAULT_OUT = Path('security_ir_artifacts/production/blocker-evidence-packets.json')
DOC_PATH = 'docs/security_verification/production_blocker_evidence_packets.md'
VALIDATION_COMMAND = (
    'PYTHONPATH=. /home/barberb/miniforge3/bin/python '
    'scripts/ops/security_verification/validate_production_evidence_bundle.py '
    '--schema security_ir_artifacts/production/evidence-bundle.schema.json '
    '--bundle <production-evidence-bundle.json> '
    '--out <production-evidence-validation-report.json>'
)
GENERATOR_VALIDATION_COMMAND = (
    'PYTHONPATH=. /home/barberb/miniforge3/bin/python '
    'scripts/ops/security_verification/generate_production_blocker_evidence_packets.py '
    '--bridge security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json '
    '--schema security_ir_artifacts/production/evidence-bundle.schema.json '
    '--out security_ir_artifacts/production/blocker-evidence-packets.json'
)

PRODUCTION_EVIDENCE_DOMAINS = (
    'production_source',
    'production_build',
    'production_runtime',
    'production_environment',
    'human_review',
)

DOMAIN_TO_BUNDLE_CATEGORY = {
    'production_source': 'source_snapshots',
    'production_build': 'source_snapshots',
    'production_runtime': 'runtime_traces',
    'production_environment': 'environment_evidence',
    'human_review': 'owner_signoff',
}

DOMAIN_OWNER = {
    'production_source': 'mobile-appsec-source-owner',
    'production_build': 'release-engineering-owner',
    'production_runtime': 'runtime-assurance-owner',
    'production_environment': 'production-security-operations-owner',
    'human_review': 'named-security-release-owner',
}

DOMAIN_FRESHNESS_DAYS = {
    'production_source': 30,
    'production_build': 14,
    'production_runtime': 7,
    'production_environment': 30,
    'human_review': 14,
}

DOMAIN_REQUIRED_BUNDLE_FIELDS = {
    'production_source': (
        'id',
        'repository',
        'commit',
        'path',
        'sha256',
        'collected_at_utc',
        'owner',
        'review_status',
    ),
    'production_build': (
        'id',
        'repository',
        'commit',
        'path',
        'sha256',
        'collected_at_utc',
        'owner',
        'review_status',
        'description',
    ),
    'production_runtime': (
        'id',
        'stream',
        'path',
        'sha256',
        'collected_at_utc',
        'window_start_utc',
        'window_end_utc',
        'owner',
        'review_status',
    ),
    'production_environment': (
        'id',
        'environment',
        'path',
        'sha256',
        'collected_at_utc',
        'owner',
        'review_status',
    ),
    'human_review': (
        'id',
        'scope',
        'owner',
        'role',
        'decision',
        'signed_at_utc',
        'statement',
    ),
}

DOMAIN_BASE_REQUESTS = {
    'production_source': (
        'Reviewed production source inventory for the exact release boundary, including native modules, backend services, dependencies, policy files, and vendor code that can affect this blocker.',
        'Human-reviewed diff or source attestation proving the release source contains the implementation being evaluated by the evidence packet.',
    ),
    'production_build': (
        'Signed build provenance, reproducible-build output, CI/CD attestation, deployment digest, or app-store binary attestation tying the reviewed source to the deployed artifact.',
        'Binary-to-source or deployment-to-commit binding for every platform or service that can affect this blocker.',
    ),
    'production_runtime': (
        'Release-window runtime traces, integration traces, ledger/backend execution traces, or real-device traces bound to the deployed build and covering this blocker behavior.',
        'Trace extraction report with collection window, environment, device or service identity, and reviewed monitor version.',
    ),
    'production_environment': (
        'Production environment profile covering platform, custody, network, node, solver, secret-management, backend, and operational configuration relevant to this blocker.',
        'Configuration evidence or probe report proving the environment used for validation matches the deployed release environment.',
    ),
    'human_review': (
        'Named accountable owner signoff accepting evidence scope, freshness, release binding, residual risk, and blocker-specific closure criteria.',
        'Security review decision that references the production evidence bundle and explicitly rejects Xaman source-corpus-only closure.',
    ),
}


def _slug(value: str) -> str:
    slug = ''.join(ch if ch.isalnum() else '-' for ch in value.lower()).strip('-')
    while '--' in slug:
        slug = slug.replace('--', '-')
    return slug


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return payload


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _fallback_mapping(
    blocker_id: str,
    *,
    category: str,
    severity: str,
    blocked_claim_ids: Sequence[str],
    reason: str,
    requirements: Sequence[str],
    domains: Sequence[str],
    blocker_type: str = 'blocking_assumption',
) -> dict[str, Any]:
    return {
        'id': f'bridge:{_slug(blocker_id)}',
        'source_packet_blocker_id': blocker_id,
        'type': blocker_type,
        'category': category,
        'severity': severity,
        'reason': reason,
        'release_effect': 'blocked-production',
        'blocked_claim_ids': list(blocked_claim_ids),
        'removal_status': 'blocked_missing_production_evidence',
        'source_corpus_evidence_status': 'mapped-but-insufficient-for-production',
        'deployed_app_evidence_status': 'missing',
        'required_evidence_to_close_from_packet': list(requirements),
        'required_production_evidence_domains': list(domains),
        'domain_requirements': [
            {
                'domain': domain,
                'status': 'missing',
                'description': '',
                'source_packet_requirements': list(requirements),
            }
            for domain in domains
        ],
    }


def build_fallback_bridge() -> dict[str, Any]:
    """Return canonical bridge-like metadata used when dependency artifacts are absent."""

    mappings = [
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-native-vault-cryptographic-confidentiality',
            category='custody',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:custody-software-private-key-not-available-without-authorized-vault-path'],
            reason='The reviewed artifact only models the TypeScript vault facade, not the native implementation or platform keychain/keystore policy.',
            requirements=[
                'Native VaultManagerModule source review for iOS and Android.',
                'Keychain/Keystore access-control, encryption, migration, and backup policy evidence.',
                'Runtime or binary-equivalence evidence proving the reviewed native module is deployed.',
            ],
            domains=PRODUCTION_EVIDENCE_DOMAINS,
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-passcode-kdf-and-secret-protection',
            category='authentication',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:authentication-gates-vault-and-signing'],
            reason='The reviewed source facts show passcode hashing and throttling, but not the KDF algorithm, salt handling, parameters, or stored-hash protection.',
            requirements=[
                'Reviewed KDF implementation and parameter evidence.',
                'Evidence that stored passcode material is encrypted or hardware-bound.',
                'Attack-cost analysis for the supported passcode policy.',
            ],
            domains=('production_source', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-biometric-native-binding',
            category='authentication',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:authentication-gates-vault-and-signing'],
            reason='The reviewed facts cover app-level biometric checks, not native prompt integrity, secure hardware binding, enrollment-change enforcement, or spoof resistance.',
            requirements=[
                'Native biometric prompt and enrollment-binding source review.',
                'Platform security policy for biometric unlock fallback and revocation.',
                'Runtime tests for enrollment change and inactive-app rejection.',
            ],
            domains=('production_source', 'production_runtime', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-third-party-signing-correctness',
            category='signing',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent'],
            reason='Source-corpus facts describe third-party signing intent handling but do not prove deployed third-party signing integrations preserve reviewed intent.',
            requirements=[
                'Reviewed production source for third-party signing request construction and result handling.',
                'Runtime traces for accepted, rejected, expired, and malformed third-party signing flows.',
                'Owner review of supported third-party signing providers and residual trust assumptions.',
            ],
            domains=('production_source', 'production_runtime', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-backend-payload-api-single-use-and-authorization',
            category='backend',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:payload-replay-prevention-is-single-use'],
            reason='The source corpus models payload API expectations without deployed backend authorization, persistence, replay, and revocation evidence.',
            requirements=[
                'Production backend source and policy review for payload authorization and single-use state transitions.',
                'Runtime traces for create, resolve, sign, reject, expire, and replay-attempt payload paths.',
                'Environment evidence for backend storage, cache, queue, and API gateway configuration.',
            ],
            domains=('production_source', 'production_runtime', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-intake-decoder-and-os-delivery-integrity',
            category='payload-intake',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:payload-integrity-before-review-and-signing'],
            reason='The reviewed corpus does not bind QR, deep-link, push, and OS delivery decoding behavior to production devices and builds.',
            requirements=[
                'Reviewed decoder and OS delivery source for QR, deep link, push, and handoff inputs.',
                'Real-device runtime traces showing malformed, replayed, and cross-network payload intake rejection.',
                'Platform and notification environment evidence for supported iOS and Android releases.',
            ],
            domains=('production_source', 'production_runtime', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-deployed-network-and-node-config-equivalence',
            category='network',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:network-binding-prevents-cross-network-signing'],
            reason='Source-corpus network facts are not evidence that deployed clients and backend services use the reviewed XRPL network and node configuration.',
            requirements=[
                'Release build or deployment provenance for network selection and node configuration.',
                'Runtime traces proving mainnet/testnet/devnet payloads bind to the intended configured network.',
                'Production node, RPC, and feature-flag configuration evidence.',
            ],
            domains=('production_build', 'production_runtime', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-trustset-and-signerlist-client-validation',
            category='xrpl-client-validation',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent'],
            reason='The corpus does not prove production clients validate trustset and signerlist semantics before human review and signing.',
            requirements=[
                'Reviewed source for trustset, signerlist, multisign, and account-authority validation paths.',
                'Runtime traces covering accepted and rejected trustline and signer-list transaction intents.',
                'Human review of XRPL transaction semantics coverage and residual parser risk.',
            ],
            domains=('production_source', 'production_runtime', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-xrpl-server-rule-enforcement-and-consensus',
            category='xrpl-consensus',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent'],
            reason='Reviewed source cannot prove production XRPL servers and consensus rules enforce the transaction constraints assumed by the model.',
            requirements=[
                'Production XRPL server, amendment, network, and RPC provider configuration evidence.',
                'Ledger execution traces or integration tests showing consensus rejection for invalid transaction cases.',
                'Owner review of external ledger trust and failover assumptions.',
            ],
            domains=('production_runtime', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-external-multisign-coordination',
            category='multisign',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent'],
            reason='External multisign coordination is outside the reviewed source corpus and needs deployed integration evidence.',
            requirements=[
                'Reviewed production source for multisign coordination, signer identity, and threshold handling.',
                'Runtime traces for quorum success, signer rejection, stale request, and malicious signer scenarios.',
                'Environment evidence for external signer endpoints, custody boundaries, and operational runbooks.',
            ],
            domains=('production_source', 'production_runtime', 'production_environment', 'human_review'),
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-deployed-runtime-equivalence',
            category='runtime-equivalence',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime'],
            reason='The source packet proves only what was reviewed; it does not prove that the reviewed code is the code running in production.',
            requirements=[
                'Reproducible build or signed binary provenance for each production app and backend artifact.',
                'Production source inventory and deployment manifest for the exact release.',
                'Release-window runtime traces from the deployed artifacts.',
            ],
            domains=PRODUCTION_EVIDENCE_DOMAINS,
        ),
        _fallback_mapping(
            'blocker:assumption:xaman-security-assumption-proof-receipt-cid-or-signature-validation',
            category='proof-consumer',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims'],
            reason='The proof-consumer fixture is not evidence that production consumers validate proof receipt CIDs or signatures fail-closed.',
            requirements=[
                'Reviewed production proof-consumer source and receipt/signature validation policy.',
                'Build provenance proving the reviewed proof consumer is deployed.',
                'Runtime traces for valid receipt, wrong CID, missing signature, stale evidence, and solver-mismatch rejection.',
            ],
            domains=PRODUCTION_EVIDENCE_DOMAINS,
        ),
        _fallback_mapping(
            'blocker:proof:no-critical-claim-proved',
            category='proof',
            severity='blocking',
            blocked_claim_ids=[
                'xaman-security:claim:custody-software-private-key-not-available-without-authorized-vault-path',
                'xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime',
            ],
            reason='No critical production claim has a current accepted prove outcome bound to deployed-app evidence.',
            requirements=[
                'Solver-backed prove reports for every blocking and high production claim.',
                'Current production source, build, runtime, and environment evidence bound to each proof report.',
                'Named human review accepting proof scope, assumptions, and release binding.',
            ],
            domains=PRODUCTION_EVIDENCE_DOMAINS,
            blocker_type='proof_blocker',
        ),
        _fallback_mapping(
            'blocker:solver:apalache',
            category='apalache',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:payload-replay-prevention-is-single-use'],
            reason='The Apalache/TLA lane is unavailable, so temporal payload and runtime claims cannot be accepted for production.',
            requirements=[
                'Reviewed Apalache installation or probe report for the production verification environment.',
                'Regenerated TLA report showing required claims are proved or explicitly fail-closed.',
            ],
            domains=('production_environment', 'human_review'),
            blocker_type='solver_blocker',
        ),
        _fallback_mapping(
            'blocker:solver:proverif',
            category='proverif',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:backend-trust-boundary-is-safe-for-payload-resolution'],
            reason='The ProVerif protocol lane is unavailable, so protocol secrecy and correspondence claims cannot be accepted.',
            requirements=[
                'Reviewed ProVerif installation or probe report for the production verification environment.',
                'Regenerated protocol proof report for the payload lifecycle model.',
            ],
            domains=('production_environment', 'human_review'),
            blocker_type='solver_blocker',
        ),
        _fallback_mapping(
            'blocker:solver:tamarin-prover',
            category='tamarin-prover',
            severity='high',
            blocked_claim_ids=['xaman-security:claim:backend-trust-boundary-is-safe-for-payload-resolution'],
            reason='The Tamarin protocol lane is unavailable, so protocol proof coverage remains degraded.',
            requirements=[
                'Reviewed Tamarin installation or probe report for the production verification environment.',
                'Regenerated Tamarin protocol proof report with reviewed solver output.',
            ],
            domains=('production_environment', 'human_review'),
            blocker_type='solver_blocker',
        ),
        _fallback_mapping(
            'blocker:runtime:real-device-traces-absent',
            category='runtime',
            severity='blocking',
            blocked_claim_ids=['xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime'],
            reason='The source packet contains no release-window iOS or Android real-device traces from the deployed app.',
            requirements=[
                'Release-window iOS and Android real-device traces for reviewed signing, rejection, replay, and network-binding flows.',
                'Build provenance tying each trace to the deployed app binary.',
                'Production environment profile for devices, OS versions, network, backend, and ledger endpoints.',
            ],
            domains=('production_build', 'production_runtime', 'production_environment', 'human_review'),
            blocker_type='runtime_blocker',
        ),
    ]

    by_domain = {
        domain: {
            'domain': domain,
            'blocker_count': sum(
                1 for mapping in mappings if domain in mapping['required_production_evidence_domains']
            ),
            'source_packet_blocker_ids': [
                mapping['source_packet_blocker_id']
                for mapping in mappings
                if domain in mapping['required_production_evidence_domains']
            ],
        }
        for domain in PRODUCTION_EVIDENCE_DOMAINS
    }
    bridge = {
        'schema_version': 'xaman-production-blocker-bridge/v1',
        'task_id': 'PORTAL-CXTP-076',
        'generated_at_utc': '2026-07-08T22:30:00Z',
        'source_packet': {
            'artifact_cid': 'fallback:xaman-assurance-packet-unavailable',
            'release_decision': 'blocked-production',
        },
        'evidence_scope': {
            'source_corpus': {
                'status': 'available_for_review_context',
                'accepted_for_deployed_app_release': False,
                'evidence_count': 0,
                'evidence': [],
            },
            'deployed_app': {
                'scope': 'deployed_app',
                'status': 'absent',
                'accepted_evidence_count': 0,
                'accepted_evidence': [],
                'real_device_trace_count': 0,
                'production_release_ready': False,
            },
        },
        'production_evidence_domains': list(PRODUCTION_EVIDENCE_DOMAINS),
        'remaining_blockers_by_domain': by_domain,
        'blocker_mappings': mappings,
        'summary': {
            'open_blocker_count': len(mappings),
            'source_packet_open_blocker_count': len(mappings),
            'remaining_domain_count': len(PRODUCTION_EVIDENCE_DOMAINS),
            'deployed_app_accepted_evidence_count': 0,
            'release_ready': False,
            'domain_blocker_counts': {
                domain: by_domain[domain]['blocker_count']
                for domain in PRODUCTION_EVIDENCE_DOMAINS
            },
        },
        'production_blocker_removal_policy': {
            'decision': 'blocked-production',
            'may_remove_any_blocker': False,
            'required_before_removal': [
                'Every mapped blocker has current evidence for each listed production evidence domain.',
                'Deployed-app evidence is separated from source-corpus evidence and reviewed independently.',
                'Every blocking/high claim has an accepted PROVED outcome bound to the release packet.',
                'Human owners accept freshness, scope, and residual risk for each blocker removal.',
            ],
        },
    }
    bridge['artifact_cid'] = _artifact_cid(bridge)
    return bridge


def _load_bridge(path: Path) -> tuple[dict[str, Any], bool]:
    bridge = _load_json(path)
    if bridge is None:
        return build_fallback_bridge(), True
    return bridge, False


def _load_schema_metadata(path: Path) -> dict[str, Any]:
    schema = _load_json(path)
    if schema is None:
        return {
            'path': path.as_posix(),
            'status': 'missing',
            'schema_version': None,
            'title': None,
        }
    return {
        'path': path.as_posix(),
        'status': 'loaded',
        'schema_version': schema.get('$id') or schema.get('properties', {}).get('schema_version', {}).get('const'),
        'title': schema.get('title'),
    }


def _domain_requirements_from_mapping(mapping: Mapping[str, Any], domain: str) -> list[str]:
    for item in mapping.get('domain_requirements', []):
        if isinstance(item, Mapping) and item.get('domain') == domain:
            values = item.get('source_packet_requirements', [])
            if isinstance(values, list) and values:
                return [str(value) for value in values]
    values = mapping.get('required_evidence_to_close_from_packet', [])
    if isinstance(values, list):
        return [str(value) for value in values]
    return []


def _evidence_request(mapping: Mapping[str, Any], domain: str) -> dict[str, Any]:
    blocker_id = str(mapping['source_packet_blocker_id'])
    packet_specific = _domain_requirements_from_mapping(mapping, domain)
    return {
        'domain': domain,
        'status': 'requested',
        'evidence_bundle_category': DOMAIN_TO_BUNDLE_CATEGORY[domain],
        'expected_owner': DOMAIN_OWNER[domain],
        'freshness_window_days': DOMAIN_FRESHNESS_DAYS[domain],
        'accepted_review_statuses': ['human_reviewed', 'trusted_fixture']
        if domain != 'human_review'
        else ['approved-owner-signoff'],
        'required_bundle_fields': list(DOMAIN_REQUIRED_BUNDLE_FIELDS[domain]),
        'validator_command': VALIDATION_COMMAND,
        'must_be_bound_to_deployed_release': True,
        'required_evidence': [
            *DOMAIN_BASE_REQUESTS[domain],
            *[
                f'Blocker-specific evidence: {requirement}'
                for requirement in packet_specific
            ],
        ],
        'rejection_rules': [
            'Reject placeholder, ownerless, stale, unsigned, or unreviewed evidence.',
            'Reject evidence that is not bound to the exact production release, deployed binary, runtime window, or environment under review.',
            'Reject Xaman source-corpus-only evidence because it is review context, not deployed-app evidence.',
        ],
        'packet_reference': {
            'source_packet_blocker_id': blocker_id,
            'bridge_mapping_id': mapping.get('id'),
        },
    }


def _why_source_corpus_insufficient(mapping: Mapping[str, Any]) -> str:
    blocker_id = str(mapping.get('source_packet_blocker_id', '<unknown>'))
    reason = str(mapping.get('reason', 'the blocker requires deployed-app evidence'))
    domains = ', '.join(str(domain) for domain in mapping.get('required_production_evidence_domains', []))
    return (
        f'Xaman source-corpus evidence cannot remove {blocker_id}: {reason} '
        f'The bridge marks source evidence as {mapping.get("source_corpus_evidence_status", "insufficient")} '
        f'and deployed-app evidence as {mapping.get("deployed_app_evidence_status", "missing")}. '
        f'The blocker requires current deployed-app evidence across: {domains}.'
    )


def _packet_from_mapping(mapping: Mapping[str, Any], index: int) -> dict[str, Any]:
    domains = [
        str(domain)
        for domain in mapping.get('required_production_evidence_domains', [])
        if domain in PRODUCTION_EVIDENCE_DOMAINS
    ]
    if not domains:
        raise ValueError(f'bridge mapping {mapping.get("source_packet_blocker_id", index)!r} has no valid domains')

    source_blocker_id = str(mapping['source_packet_blocker_id'])
    requests = [_evidence_request(mapping, domain) for domain in domains]
    freshness = {
        domain: DOMAIN_FRESHNESS_DAYS[domain]
        for domain in domains
    }
    owners = {
        domain: DOMAIN_OWNER[domain]
        for domain in domains
    }
    packet = {
        'id': f'evidence-request:{_slug(source_blocker_id)}',
        'request_id': f'evidence-request:{_slug(source_blocker_id)}',
        'ordinal': index + 1,
        'source_packet_blocker_id': source_blocker_id,
        'blocker_id': source_blocker_id,
        'production_blocker_id': source_blocker_id,
        'source_task_id': 'PORTAL-CXTP-076',
        'source_blocker_status': mapping.get('removal_status', 'blocked_missing_production_evidence'),
        'bridge_mapping_id': mapping.get('id'),
        'category': mapping.get('category'),
        'type': mapping.get('type'),
        'severity': mapping.get('severity'),
        'release_effect': 'blocked-production',
        'release_gate_effect': 'fail_closed',
        'production_release_effect': 'blocked-production',
        'blocking_behavior': 'release_blocking',
        'until': 'reviewed_production_evidence_supplied',
        'blocked_claim_ids': list(mapping.get('blocked_claim_ids', [])),
        'claim_ids': list(mapping.get('blocked_claim_ids', [])),
        'required_production_evidence_domains': domains,
        'required_evidence_categories': domains,
        'expected_owners': owners,
        'freshness_windows_days': freshness,
        'validator_command': VALIDATION_COMMAND,
        'evidence_requests': requests,
        'source_packet_closure_requirements': list(
            mapping.get('required_evidence_to_close_from_packet', [])
        ),
        'xaman_source_corpus_boundary': {
            'status': 'insufficient-for-production-unblock',
            'source_corpus_evidence_status': mapping.get('source_corpus_evidence_status'),
            'deployed_app_evidence_status': mapping.get('deployed_app_evidence_status'),
            'why_xaman_source_corpus_alone_cannot_remove_blocker': _why_source_corpus_insufficient(mapping),
        },
        'closure_policy': {
            'may_close_from_this_packet': False,
            'unblocks': [],
            'required_before_status_update': [
                'A production evidence bundle validates with no blockers.',
                'Every required domain in this packet is present in the bundle.',
                'Every blocking/high claim affected by this blocker has outcome prove.',
                'Named human review is current and approves the blocker-specific evidence.',
            ],
        },
    }
    packet['packet_cid'] = _artifact_cid(packet)
    return packet


def _validate_bridge_shape(bridge: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    mappings = bridge.get('blocker_mappings')
    if not isinstance(mappings, list) or not mappings:
        raise ValueError('bridge must contain a non-empty blocker_mappings list')
    seen: set[str] = set()
    valid: list[Mapping[str, Any]] = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, Mapping):
            raise ValueError(f'bridge blocker_mappings[{index}] must be an object')
        blocker_id = mapping.get('source_packet_blocker_id')
        if not isinstance(blocker_id, str) or not blocker_id:
            raise ValueError(f'bridge blocker_mappings[{index}] is missing source_packet_blocker_id')
        if blocker_id in seen:
            raise ValueError(f'duplicate bridge blocker mapping: {blocker_id}')
        seen.add(blocker_id)
        valid.append(mapping)
    return valid


def build_production_blocker_evidence_packets(
    bridge: Mapping[str, Any],
    *,
    bridge_path: Path = DEFAULT_BRIDGE,
    schema_path: Path = DEFAULT_SCHEMA,
    bridge_missing_fallback_used: bool = False,
    generated_at_utc: str = FIXED_GENERATED_AT_UTC,
) -> dict[str, Any]:
    """Build the deterministic PORTAL-CXTP-094 packet artifact."""

    mappings = _validate_bridge_shape(bridge)
    packets = [_packet_from_mapping(mapping, index) for index, mapping in enumerate(mappings)]
    domain_counts = {
        domain: sum(1 for packet in packets if domain in packet['required_production_evidence_domains'])
        for domain in PRODUCTION_EVIDENCE_DOMAINS
    }
    payload = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc,
        'artifact_type': 'production_blocker_evidence_request_packets',
        'document_path': DOC_PATH,
        'source_bridge': {
            'path': bridge_path.as_posix(),
            'status': 'fallback-synthesized' if bridge_missing_fallback_used else 'loaded',
            'schema_version': bridge.get('schema_version'),
            'task_id': bridge.get('task_id'),
            'artifact_cid': bridge.get('artifact_cid'),
            'source_packet_artifact_cid': (
                bridge.get('source_packet', {}).get('artifact_cid')
                if isinstance(bridge.get('source_packet'), Mapping)
                else None
            ),
        },
        'evidence_bundle_schema': _load_schema_metadata(schema_path),
        'production_release_decision': 'blocked-production',
        'production_release_effect': 'blocked-production',
        'overall_status': 'blocked',
        'release_gate_effect': 'fail_closed',
        'proof_acceptance_blocked': True,
        'may_remove_any_blocker': False,
        'validator_command': VALIDATION_COMMAND,
        'generation_validation_command': GENERATOR_VALIDATION_COMMAND,
        'summary': {
            'remaining_blocker_count': len(packets),
            'blocker_count': len(packets),
            'packet_count': len(packets),
            'request_count': len(packets),
            'production_evidence_domain_count': len(PRODUCTION_EVIDENCE_DOMAINS),
            'domain_blocker_counts': domain_counts,
            'all_packets_require_human_review': all(
                'human_review' in packet['required_production_evidence_domains']
                for packet in packets
            ),
            'xaman_source_corpus_accepted_for_production_unblock': False,
            'deployed_app_evidence_required': True,
        },
        'freshness_policy': {
            'domain_windows_days': deepcopy(DOMAIN_FRESHNESS_DAYS),
            'strictest_window_days': min(DOMAIN_FRESHNESS_DAYS.values()),
            'longest_window_days': max(DOMAIN_FRESHNESS_DAYS.values()),
        },
        'expected_owner_registry': deepcopy(DOMAIN_OWNER),
        'packets': packets,
        'evidence_request_packets': packets,
        'packet_index': {
            packet['source_packet_blocker_id']: packet['id']
            for packet in packets
        },
    }
    payload['artifact_cid'] = _artifact_cid(payload)
    return payload


def render_markdown(payload: Mapping[str, Any]) -> str:
    packets = payload.get('packets', [])
    if not isinstance(packets, list):
        packets = []
    lines = [
        '# Production Blocker Evidence Packets',
        '',
        f'Task: `{TASK_ID}`',
        '',
        f'Generated artifact: `security_ir_artifacts/production/blocker-evidence-packets.json`',
        f'Packet schema: `{SCHEMA_VERSION}`',
        f'Artifact CID: `{payload.get("artifact_cid")}`',
        f'Production release effect: `{payload.get("production_release_effect")}`',
        f'Release gate effect: `{payload.get("release_gate_effect")}`',
        '',
        'These packets are evidence requests. They do not close production blockers. '
        'A later status updater may only propose a blocker change after a production evidence bundle validates with no blockers and every required domain in the relevant packet is present.',
        '',
        '## Validation',
        '',
        f'- Regenerate packets: `{payload.get("generation_validation_command")}`',
        f'- Validate collected production evidence: `{payload.get("validator_command")}`',
        '',
        '## Evidence Domains',
        '',
        '| Domain | Bundle category | Expected owner | Freshness window |',
        '| --- | --- | --- | --- |',
    ]
    owner_registry = payload.get('expected_owner_registry', {})
    freshness = payload.get('freshness_policy', {}).get('domain_windows_days', {})
    for domain in PRODUCTION_EVIDENCE_DOMAINS:
        lines.append(
            '| `{}` | `{}` | `{}` | `{}` days |'.format(
                domain,
                DOMAIN_TO_BUNDLE_CATEGORY[domain],
                owner_registry.get(domain, DOMAIN_OWNER[domain]),
                freshness.get(domain, DOMAIN_FRESHNESS_DAYS[domain]),
            )
        )

    lines.extend(
        [
            '',
            '## Xaman Source-Corpus Boundary',
            '',
            'The Xaman source-corpus packet is review context only. It can identify the blocker and its closure criteria, but it does not prove deployed-app source equivalence, signed build provenance, release-window runtime behavior, production environment configuration, or named owner acceptance.',
            '',
            '## Packet Inventory',
            '',
            '| # | Blocker | Severity | Required domains | Why source-corpus evidence alone is insufficient |',
            '| --- | --- | --- | --- | --- |',
        ]
    )
    for packet in packets:
        boundary = packet.get('xaman_source_corpus_boundary', {}) if isinstance(packet, Mapping) else {}
        why = str(boundary.get('why_xaman_source_corpus_alone_cannot_remove_blocker', ''))
        lines.append(
            '| `{}` | `{}` | `{}` | `{}` | {} |'.format(
                packet.get('ordinal'),
                packet.get('source_packet_blocker_id'),
                packet.get('severity'),
                ', '.join(f'`{domain}`' for domain in packet.get('required_production_evidence_domains', [])),
                why.replace('|', '\\|'),
            )
        )

    lines.extend(['', '## Packet Details', ''])
    for packet in packets:
        lines.extend(
            [
                f'### {packet.get("ordinal")}. `{packet.get("source_packet_blocker_id")}`',
                '',
                f'- Packet ID: `{packet.get("id")}`',
                f'- Severity: `{packet.get("severity")}`',
                f'- Expected owners: `{json.dumps(packet.get("expected_owners", {}), sort_keys=True)}`',
                f'- Freshness windows: `{json.dumps(packet.get("freshness_windows_days", {}), sort_keys=True)}`',
                f'- Validator command: `{packet.get("validator_command")}`',
                f'- Xaman insufficiency: {packet.get("xaman_source_corpus_boundary", {}).get("why_xaman_source_corpus_alone_cannot_remove_blocker")}',
                '',
                '| Domain | Required evidence |',
                '| --- | --- |',
            ]
        )
        for request in packet.get('evidence_requests', []):
            required = '<br>'.join(str(item) for item in request.get('required_evidence', []))
            escaped_required = required.replace('|', '\\|')
            lines.append(f'| `{request.get("domain")}` | {escaped_required} |')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge', default=DEFAULT_BRIDGE.as_posix(), help='Xaman production blocker bridge JSON')
    parser.add_argument('--schema', default=DEFAULT_SCHEMA.as_posix(), help='Production evidence bundle schema JSON')
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='Output packet JSON path')
    parser.add_argument('--doc-out', default=DOC_PATH, help='Output Markdown document path')
    parser.add_argument(
        '--generated-at-utc',
        default=FIXED_GENERATED_AT_UTC,
        help='Deterministic generated_at_utc timestamp for checked-in artifacts',
    )
    parser.add_argument(
        '--no-doc',
        action='store_true',
        help='Only write JSON, not the Markdown companion document',
    )
    args = parser.parse_args(argv)

    bridge_path = Path(args.bridge)
    schema_path = Path(args.schema)
    bridge, fallback_used = _load_bridge(bridge_path)
    payload = build_production_blocker_evidence_packets(
        bridge,
        bridge_path=bridge_path,
        schema_path=schema_path,
        bridge_missing_fallback_used=fallback_used,
        generated_at_utc=args.generated_at_utc,
    )
    out_path = Path(args.out)
    write_json(out_path, payload)
    if not args.no_doc:
        doc_path = Path(args.doc_out)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_markdown(payload), encoding='utf-8')
    print(
        json.dumps(
            {
                'status': 'ok',
                'out': out_path.as_posix(),
                'packet_count': payload['summary']['packet_count'],
                'artifact_cid': payload['artifact_cid'],
                'bridge_status': payload['source_bridge']['status'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
