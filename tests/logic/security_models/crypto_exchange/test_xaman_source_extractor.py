import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_source_extractor import (
    SCHEMA_VERSION,
    XamanSourceExtractor,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CHECKED_IN_COVERAGE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-coverage.json'
)
CHECKED_IN_MANIFEST_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-manifest.json'
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _manifest(root: Path, paths: list[str]) -> dict[str, Any]:
    files = []
    for path in paths:
        full_path = root / path
        files.append(
            {
                'path': path,
                'size_bytes': full_path.stat().st_size if full_path.exists() else 0,
                'sha256': '0' * 64,
            }
        )
    return {
        'schema_version': 'xaman-corpus-source-manifest/v1',
        'corpus': 'xaman-app',
        'source': {
            'repo_url': 'https://github.com/XRPL-Labs/Xaman-App',
            'commit_sha': '942f43876265a7af44f233288ad2b1d00841d5fa',
        },
        'reproducibility': {'aggregate_sha256': '1' * 64},
        'files': files,
    }


def test_xaman_source_extractor_parses_aliases_typescript_tsx_and_e2e_flows(tmp_path: Path) -> None:
    _write(
        tmp_path / 'tsconfig.json',
        json.dumps(
            {
                'compilerOptions': {
                    'baseUrl': '.',
                    'paths': {
                        '@services/*': ['src/services/*'],
                        '@payload': ['src/common/libs/payload/index'],
                        '@ledger/*': ['src/common/libs/ledger/*'],
                    },
                }
            }
        ),
    )
    _write(tmp_path / 'src/services/package.json', '{"name":"services"}\n')
    _write(
        tmp_path / 'src/services/AuthenticationService.ts',
        '''
import { PayloadDigest } from '@payload';
import { LedgerSigner } from '@ledger/mixin/Sign.mixin';
import { Vault } from '../common/libs/vault';

/** Every authentication challenge must be authorized before signing. */
export class AuthenticationService {
  authorizeSession(authorized: boolean): boolean {
    if (!authorized) {
      throw new Error('authorization required');
    }
    return true;
  }
}

/** Signing must be authorized and audited. */
export function signWithVault(authorized: boolean, auditLog: { emit(name: string): void }): boolean {
  if (!authorized) {
    throw new Error('authorization required');
  }
  auditLog.emit('signed');
  return true;
}
''',
    )
    _write(
        tmp_path / 'src/common/libs/payload/index.ts',
        '''
export class PayloadDigest {}
export function verifyPayloadDigest(authorized: boolean): boolean {
  if (!authorized) throw new Error('authorization required');
  return true;
}
''',
    )
    _write(
        tmp_path / 'src/common/libs/ledger/mixin/Sign.mixin.ts',
        '''
export class LedgerSigner {}
export function submitSignedTransaction(authorized: boolean): boolean {
  if (!authorized) throw new Error('authorization required');
  return true;
}
''',
    )
    _write(
        tmp_path / 'src/common/libs/vault.ts',
        '''
export class Vault {}
export function unlockVault(authorized: boolean): boolean {
  if (!authorized) throw new Error('authorization required');
  return true;
}
''',
    )
    _write(
        tmp_path / 'src/screens/Overlay/Authenticate/AuthenticateOverlay.tsx',
        '''
import { signWithVault } from '@services/AuthenticationService';

/** Authentication UI must require consent before signing. */
export function AuthenticateOverlay(): JSX.Element {
  return null as unknown as JSX.Element;
}
''',
    )
    _write(
        tmp_path / 'e2e/05_auth.feature',
        '''
Feature: Authenticate signing
  Scenario: User approves a payload with biometrics
    Given the wallet is unlocked
    When the user approves the payload
    Then the payload is signed
''',
    )
    _write(tmp_path / 'src/store/package.json', '{"name":"store"}\n')

    manifest = _manifest(
        tmp_path,
        [
            'tsconfig.json',
            'src/services/package.json',
            'src/services/AuthenticationService.ts',
            'src/common/libs/payload/index.ts',
            'src/common/libs/ledger/mixin/Sign.mixin.ts',
            'src/common/libs/vault.ts',
            'src/screens/Overlay/Authenticate/AuthenticateOverlay.tsx',
            'e2e/05_auth.feature',
            'src/store/package.json',
        ],
    )
    manifest_path = tmp_path / 'source-manifest.json'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    coverage = XamanSourceExtractor().extract_coverage(corpus_root=tmp_path, manifest_path=manifest_path)

    assert coverage['schema_version'] == SCHEMA_VERSION
    assert coverage['coverage_summary']['parsed_files'] == 6
    assert coverage['coverage_summary']['security_relevant_files'] == 8
    assert coverage['coverage_summary']['unsupported_files'] == 2
    assert {alias['alias'] for alias in coverage['path_aliases']} >= {
        '@services/*',
        '@payload',
        '@ledger/*',
        'services',
        'services/*',
    }

    auth_module = next(
        module
        for module in coverage['security_relevant_modules']
        if module['path'] == 'src/screens/Overlay/Authenticate/AuthenticateOverlay.tsx'
    )
    assert auth_module['category'] == 'auth_component'
    assert auth_module['parse_status'] == 'parsed'
    assert any(item['specifier'] == '@services/AuthenticationService' for item in auth_module['resolved_imports'])
    assert any(item['resolved_path'] == 'src/services/AuthenticationService' for item in auth_module['resolved_imports'])
    assert any(symbol['name'] == 'AuthenticateOverlay' for symbol in auth_module['symbols'])

    service_module = next(
        module
        for module in coverage['security_relevant_modules']
        if module['path'] == 'src/services/AuthenticationService.ts'
    )
    assert service_module['category'] == 'service'
    assert 'authentication' in service_module['security_tags']
    assert any(symbol['name'] == 'AuthenticationService' for symbol in service_module['symbols'])
    assert any(policy['name'] == 'authorization_required' for policy in service_module['policies'])

    e2e_module = next(module for module in coverage['security_relevant_modules'] if module['path'] == 'e2e/05_auth.feature')
    assert e2e_module['parse_status'] == 'parsed'
    assert e2e_module['parser'] == 'gherkin_feature'
    assert any(symbol['kind'] == 'scenario' for symbol in e2e_module['symbols'])

    assert coverage['coverage_gaps']
    assert all(gap['review_status'] == 'reviewed_gap' for gap in coverage['coverage_gaps'])


def test_xaman_source_extractor_manifest_only_records_reviewed_gaps(tmp_path: Path) -> None:
    manifest = {
        'schema_version': 'xaman-corpus-source-manifest/v1',
        'corpus': 'xaman-app',
        'source': {
            'repo_url': 'https://github.com/XRPL-Labs/Xaman-App',
            'commit_sha': '942f43876265a7af44f233288ad2b1d00841d5fa',
        },
        'reproducibility': {'aggregate_sha256': '2' * 64},
        'files': [
            {'path': 'tsconfig.json', 'size_bytes': 100, 'sha256': '3' * 64},
            {'path': 'src/services/AuthenticationService.ts', 'size_bytes': 200, 'sha256': '4' * 64},
            {'path': 'src/common/libs/ledger/transactions/fixtures/PaymentTx.json', 'size_bytes': 300, 'sha256': '5' * 64},
            {'path': 'e2e/05_auth.feature', 'size_bytes': 400, 'sha256': '6' * 64},
        ],
    }
    manifest_path = tmp_path / 'source-manifest.json'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    coverage = XamanSourceExtractor().extract_coverage(manifest_path=manifest_path)

    assert coverage['analysis_mode'] == 'manifest_only'
    assert coverage['coverage_summary']['security_relevant_files'] == 3
    assert coverage['coverage_summary']['content_unavailable_files'] == 2
    assert coverage['coverage_summary']['unsupported_files'] == 1
    assert coverage['coverage_summary']['reviewed_gap_count'] >= 4
    assert all(gap['review_status'] == 'reviewed_gap' for gap in coverage['reviewed_coverage_gaps'])
    assert {
        module['parse_status']
        for module in coverage['security_relevant_modules']
    } == {'content_unavailable', 'unsupported'}


def test_checked_in_xaman_source_coverage_artifact_is_reviewed_manifest_coverage() -> None:
    coverage = json.loads(CHECKED_IN_COVERAGE_PATH.read_text(encoding='utf-8'))
    manifest = json.loads(CHECKED_IN_MANIFEST_PATH.read_text(encoding='utf-8'))

    assert coverage['schema_version'] == SCHEMA_VERSION
    assert coverage['corpus'] == 'xaman-app'
    assert coverage['source']['commit_sha'] == manifest['source']['commit_sha']
    assert coverage['coverage_summary']['manifest_files'] == len(manifest['files'])
    assert coverage['coverage_summary']['security_relevant_files'] >= 700
    assert coverage['coverage_summary']['reviewed_gap_count'] > 0
    assert coverage['reviewed_coverage_gaps']
    assert all(gap['review_status'] == 'reviewed_gap' for gap in coverage['reviewed_coverage_gaps'])
    paths = {module['path'] for module in coverage['security_relevant_modules']}
    assert 'src/services/AuthenticationService.ts' in paths
    assert 'src/common/libs/vault.ts' in paths
    assert 'src/screens/Overlay/Authenticate/AuthenticateOverlay.tsx' in paths
    assert 'e2e/05_auth.feature' in paths
