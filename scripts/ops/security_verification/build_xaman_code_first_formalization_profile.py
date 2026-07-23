#!/usr/bin/env python3
"""Freeze the digest-bound Xaman public-source formalization profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
DEFAULT_OUT = CORPUS_DIR / 'code-first/formalization-profile.json'
INPUTS = {
    'source_manifest': CORPUS_DIR / 'source-manifest.json',
    'hydrated_coverage': CORPUS_DIR / 'source-coverage-hydrated.json',
    'source_claim_map': CORPUS_DIR / 'source-claim-map.json',
    'transaction_coverage': CORPUS_DIR / 'xrpl-transaction-coverage.json',
    'solver_environment': CORPUS_DIR / 'environment-probe.json',
    'claim_catalog': CORPUS_DIR / 'security-claims.json',
}


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _load(repo_root: Path, path: Path) -> dict[str, Any]:
    return json.loads((repo_root / path).read_text(encoding='utf-8'))


def _ref(repo_root: Path, path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'path': str(path),
        'sha256': 'sha256:' + hashlib.sha256((repo_root / path).read_bytes()).hexdigest(),
        'artifact_cid': payload.get('artifact_cid'),
        'schema_version': payload.get('schema_version'),
    }


def build_profile(repo_root: Path) -> dict[str, Any]:
    data = {name: _load(repo_root, path) for name, path in INPUTS.items()}
    manifest_source = data['source_manifest']['source']
    commit = manifest_source['commit_sha']
    repo_url = manifest_source['repo_url']
    for name in ('hydrated_coverage', 'source_claim_map', 'transaction_coverage'):
        source = data[name]['source']
        if source['commit_sha'] != commit:
            raise ValueError(f'{name} is not bound to the frozen source commit')
    hydration = data['hydrated_coverage']['hydration']
    if hydration['source_commit_verified'] != commit or not hydration['checkout_clean']:
        raise ValueError('hydrated coverage does not attest a clean frozen checkout')

    claims = data['claim_catalog']['claims']
    categories = sorted({claim['category'] for claim in claims})
    statuses = sorted({claim['status'] for claim in claims})
    assumptions = [
        {'id': 'native-custody-and-bridge', 'domain': 'native', 'classification': 'NOT_MODELED', 'owner': 'Xaman native implementation', 'scope': 'keystore, biometric, secure-enclave, vault cryptography, and native bridge semantics', 'promotion_blocking': True, 'evidence_rule': 'Must not be represented as vendor evidence or a proved fact.'},
        {'id': 'remote-payload-services', 'domain': 'backend', 'classification': 'ASSUMPTION', 'owner': 'Xaman backend operator', 'scope': 'payload authorization, atomic single-use, availability, and server-side validation', 'promotion_blocking': True, 'evidence_rule': 'Treat as adversarial or nondeterministic; never vendor evidence.'},
        {'id': 'public-source-release-equivalence', 'domain': 'deployment', 'classification': 'NOT_MODELED', 'owner': 'release and distribution operator', 'scope': 'equivalence of the pinned public commit to deployed or store binaries and configuration', 'promotion_blocking': True, 'evidence_rule': 'Public source identity is not proof of deployed equivalence.'},
        {'id': 'xrpl-consensus-and-rpc', 'domain': 'ledger', 'classification': 'ASSUMPTION', 'owner': 'XRPL validators and RPC providers', 'scope': 'consensus, finality, ordering, RPC correctness, and network availability', 'promotion_blocking': True, 'evidence_rule': 'Model as an external trust boundary, not a proved product fact.'},
    ]
    profile: dict[str, Any] = {
        'schema_version': 'xaman-code-first-formalization-profile/v1',
        'task_id': 'PORTAL-CXTP-156',
        'analysis_mode': 'public_source_code_first',
        'source': {'repo_url': repo_url, 'commit_sha': commit, 'public_source_only': True},
        'inputs': {name: _ref(repo_root, INPUTS[name], data[name]) for name in sorted(INPUTS)},
        'hydrated_coverage': data['hydrated_coverage']['coverage_summary'],
        'claim_taxonomy': {
            'categories': categories,
            'observed_source_claim_statuses': statuses,
            'formal_result_vocabulary': ['PROVED_UNDER_ASSUMPTIONS', 'DISPROVED', 'UNKNOWN', 'NOT_MODELED', 'BLOCKED'],
            'vendor_evidence_is_available': False,
        },
        'assumption_ledger': assumptions,
        'solver_environment': {
            'input': str(INPUTS['solver_environment']),
            'overall_status': data['solver_environment']['overall_status'],
            'local_only': True,
            'live_vendor_or_ledger_access_required': False,
        },
        'promotion_policy': {
            'production_release_claims_allowed': False,
            'assumptions_may_be_promoted_to_evidence': False,
            'not_modeled_may_be_promoted_to_proved': False,
            'proof_requires_digest_bound_inputs_and_named_assumptions': True,
        },
    }
    profile['profile_digest'] = _canonical_sha256(profile)
    return profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR))
    parser.add_argument('--out', default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out
    payload = build_profile(repo_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(out.relative_to(repo_root)), 'profile_digest': payload['profile_digest']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
