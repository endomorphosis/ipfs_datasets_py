import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / 'scripts/ops/security_verification/build_xaman_code_first_formalization_profile.py'
ARTIFACT = ROOT / 'security_ir_artifacts/corpora/xaman-app/code-first/formalization-profile.json'


def _module():
    spec = importlib.util.spec_from_file_location('formalization_profile', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_checked_in_profile_is_reproducible_and_digest_bound():
    checked = json.loads(ARTIFACT.read_text())
    assert checked == _module().build_profile(ROOT)
    digest = checked.pop('profile_digest')
    canonical = json.dumps(checked, sort_keys=True, separators=(',', ':')).encode()
    assert digest == 'sha256:' + hashlib.sha256(canonical).hexdigest()
    for ref in checked['inputs'].values():
        assert ref['sha256'].startswith('sha256:')
        assert (ROOT / ref['path']).is_file()


def test_profile_freezes_scope_taxonomy_and_assumption_boundaries():
    profile = json.loads(ARTIFACT.read_text())
    assert profile['source']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert profile['hydrated_coverage']['parsed_files'] == 643
    assert set(profile['inputs']) >= {'hydrated_coverage', 'source_claim_map', 'transaction_coverage', 'solver_environment'}
    assert set(profile['claim_taxonomy']['formal_result_vocabulary']) == {'PROVED_UNDER_ASSUMPTIONS', 'DISPROVED', 'UNKNOWN', 'NOT_MODELED', 'BLOCKED'}
    ledger = {entry['domain']: entry for entry in profile['assumption_ledger']}
    assert set(ledger) == {'native', 'backend', 'deployment', 'ledger'}
    assert all(item['classification'] in {'ASSUMPTION', 'NOT_MODELED'} for item in ledger.values())
    assert all('vendor evidence' in item['evidence_rule'].lower() or item['domain'] in {'deployment', 'ledger'} for item in ledger.values())
    assert profile['promotion_policy']['assumptions_may_be_promoted_to_evidence'] is False
