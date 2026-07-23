import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
FACTS_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'wallet-auth-facts.json'
)
MANIFEST_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-manifest.json'
)
COVERAGE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-coverage.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_wallet_auth_model.md'


REQUIRED_CATEGORIES = {
    'account_storage',
    'vault_access',
    'storage_encryption',
    'authentication_overlay',
    'biometric_gate',
    'passcode_gate',
    'key_custody_boundary',
    'signing_precondition',
}

REQUIRED_FACT_IDS = {
    'xaman-wallet-auth:fact:account-secret-vaulted-for-full-access',
    'xaman-wallet-auth:fact:realm-storage-encryption-key-comes-from-vault',
    'xaman-wallet-auth:fact:vault-access-is-through-native-module',
    'xaman-wallet-auth:fact:passcode-authentication-hashes-and-throttles',
    'xaman-wallet-auth:fact:authenticate-overlay-allows-passcode-or-enabled-biometrics',
    'xaman-wallet-auth:fact:biometric-authentication-requires-enabled-setting-active-app-and-device-sensor',
    'xaman-wallet-auth:fact:software-private-key-signing-requires-vault-open-with-encryption-key',
    'xaman-wallet-auth:fact:tangem-physical-signing-uses-card-session-not-local-vault-secret',
    'xaman-wallet-auth:fact:transaction-signing-preconditions-before-vault-overlay',
    'xaman-wallet-auth:fact:submit-requires-signed-blob-single-submit-and-not-aborted',
}

REQUIRED_GAP_IDS = {
    'xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation',
    'xaman-wallet-auth:gap:biometric-native-security-properties',
    'xaman-wallet-auth:gap:passcode-hash-kdf-strength',
    'xaman-wallet-auth:gap:third-party-signing-library-correctness',
    'xaman-wallet-auth:gap:source-coverage-extractor-vault-overlay-root',
    'xaman-wallet-auth:gap:runtime-and-deployed-binary-behavior',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _manifest_files() -> dict[str, dict[str, Any]]:
    manifest = _load_json(MANIFEST_PATH)
    return {entry['path']: entry for entry in manifest['files']}


def _coverage_modules() -> dict[str, dict[str, Any]]:
    coverage = _load_json(COVERAGE_PATH)
    return {entry['path']: entry for entry in coverage['security_relevant_modules']}


def test_xaman_wallet_auth_facts_schema_and_source_pin() -> None:
    facts = _load_json(FACTS_PATH)
    manifest = _load_json(MANIFEST_PATH)
    coverage = _load_json(COVERAGE_PATH)

    assert facts['schema_version'] == 'xaman-wallet-auth-facts/v1'
    assert facts['task_id'] == 'PORTAL-CXTP-064'
    assert facts['corpus'] == 'xaman-app'
    assert facts['source']['repo_url'] == manifest['source']['repo_url']
    assert facts['source']['commit_sha'] == manifest['source']['commit_sha']
    assert facts['source']['manifest_schema_version'] == manifest['schema_version']
    assert facts['source']['manifest_aggregate_sha256'] == manifest['reproducibility']['aggregate_sha256']
    assert facts['source']['coverage_schema_version'] == coverage['schema_version']
    assert facts['review']['review_status'] == 'reviewed'


def test_xaman_wallet_auth_source_inputs_are_manifest_bound_and_extend_vault_overlay_gap() -> None:
    facts = _load_json(FACTS_PATH)
    manifest_files = _manifest_files()
    coverage_modules = _coverage_modules()

    source_inputs = facts['source_inputs']
    paths = {entry['path'] for entry in source_inputs}
    assert {
        'src/common/libs/vault.ts',
        'src/store/storage.ts',
        'src/store/repositories/account.ts',
        'src/services/AuthenticationService.ts',
        'src/screens/Overlay/Authenticate/AuthenticateOverlay.tsx',
        'src/screens/Overlay/PassphraseAuthentication/PassphraseAuthenticationOverlay.tsx',
        'src/common/libs/ledger/mixin/Sign.mixin.ts',
        'src/screens/Overlay/Vault/VaultOverlay.tsx',
        'src/screens/Overlay/Vault/Methods/Passcode/PasscodeMethod.tsx',
        'src/screens/Overlay/Vault/Methods/Passphrase/PassphraseMethod.tsx',
        'src/screens/Overlay/Vault/Methods/Tangem/TangemMethod.tsx',
        'e2e/02_generate_account.feature',
        'e2e/03_import_account.feature',
        'e2e/04_upgrade_account.feature',
    } <= paths

    covered_categories = set()
    for source_input in source_inputs:
        manifest_entry = manifest_files[source_input['path']]
        assert source_input['sha256'] == manifest_entry['sha256']
        assert source_input['size_bytes'] == manifest_entry['size_bytes']
        assert source_input['categories']
        covered_categories.update(source_input['categories'])

        if source_input['coverage_parse_status'] == 'content_unavailable':
            assert coverage_modules[source_input['path']]['parse_status'] == 'content_unavailable'
        elif source_input['coverage_parse_status'] == 'not_in_xaman_source_coverage_roots':
            assert source_input['path'] not in coverage_modules
        else:
            raise AssertionError(f'Unexpected coverage status: {source_input}')

    assert REQUIRED_CATEGORIES <= covered_categories


def test_xaman_wallet_auth_model_has_required_reviewed_fact_categories() -> None:
    facts = _load_json(FACTS_PATH)

    modeled_facts = facts['modeled_facts']
    assert len(modeled_facts) >= 20
    assert {fact['id'] for fact in modeled_facts} >= REQUIRED_FACT_IDS
    assert {fact['category'] for fact in modeled_facts} >= REQUIRED_CATEGORIES
    assert all(fact['status'] == 'MODELED' for fact in modeled_facts)
    assert all(fact['summary'] and fact['normalized_fact'] for fact in modeled_facts)

    by_id = {fact['id']: fact for fact in modeled_facts}
    assert by_id[
        'xaman-wallet-auth:fact:account-secret-vaulted-for-full-access'
    ]['normalized_fact']['stores_secret_in'] == 'native_vault'
    assert by_id[
        'xaman-wallet-auth:fact:readonly-and-tangem-accounts-do-not-store-software-private-key-on-add'
    ]['normalized_fact']['software_private_key_required_on_add'] is False
    assert by_id[
        'xaman-wallet-auth:fact:realm-storage-encryption-key-comes-from-vault'
    ]['normalized_fact']['key_length_bytes'] == 64
    assert by_id[
        'xaman-wallet-auth:fact:passcode-authentication-hashes-and-throttles'
    ]['normalized_fact']['backoff_threshold_attempts'] == 6
    assert by_id[
        'xaman-wallet-auth:fact:software-private-key-signing-requires-vault-open-with-encryption-key'
    ]['normalized_fact']['private_key_loaded_into_js_for_signing'] is True
    assert by_id[
        'xaman-wallet-auth:fact:tangem-physical-signing-uses-card-session-not-local-vault-secret'
    ]['normalized_fact']['local_vault_open'] is False


def test_xaman_wallet_auth_evidence_refs_are_reviewed_and_manifest_hashed() -> None:
    facts = _load_json(FACTS_PATH)
    manifest_files = _manifest_files()
    source_input_paths = {entry['path'] for entry in facts['source_inputs']}

    all_entries = facts['modeled_facts'] + facts['not_modeled_gaps']
    for entry in all_entries:
        assert entry['evidence'], entry['id']
        for evidence in entry['evidence']:
            assert evidence['review_status'] == 'reviewed'
            assert evidence['line_start'] >= 1
            assert evidence['line_end'] >= evidence['line_start']
            if evidence['kind'] == 'source_code':
                assert evidence['path'] in source_input_paths
                assert evidence['sha256'] == manifest_files[evidence['path']]['sha256']
            elif evidence['kind'] == 'source_manifest':
                assert evidence['path'] == 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
                assert evidence['sha256'] == facts['source']['manifest_aggregate_sha256']
            else:
                raise AssertionError(f'Unexpected evidence kind: {evidence}')


def test_xaman_wallet_auth_marks_unsupported_boundaries_not_modeled() -> None:
    facts = _load_json(FACTS_PATH)
    gaps = facts['not_modeled_gaps']

    assert {gap['id'] for gap in gaps} >= REQUIRED_GAP_IDS
    assert all(gap['status'] == 'NOT_MODELED' for gap in gaps)
    assert all(gap['required_evidence_to_model'] for gap in gaps)
    assert {
        'vault_access',
        'biometric_gate',
        'passcode_gate',
        'signing_precondition',
        'authentication_overlay',
        'account_storage',
    } <= {gap['category'] for gap in gaps}

    boundary = facts['derived_security_boundary']
    assert any('Native keychain' in item for item in boundary['not_claimed'])
    assert any('Passcode KDF' in item for item in boundary['not_claimed'])
    assert any('Tangem SDK' in item for item in boundary['not_claimed'])


def test_xaman_wallet_auth_document_covers_artifact_and_gaps() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    facts = _load_json(FACTS_PATH)

    assert 'PORTAL-CXTP-064' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json' in doc
    assert facts['source']['commit_sha'] in doc
    assert 'NOT_MODELED' in doc
    for section in [
        'Account Storage',
        'Vault And Storage',
        'Authentication Overlays',
        'Signing Preconditions',
    ]:
        assert section in doc
