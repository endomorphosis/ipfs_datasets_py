from pathlib import Path

import pytest


def test_security_logic_workflow_yaml_parses_if_pyyaml_is_available() -> None:
    yaml = pytest.importorskip('yaml')
    workflow_path = Path(__file__).resolve().parents[4] / '.github' / 'workflows' / 'security-logic-ci.yml'
    payload = yaml.safe_load(workflow_path.read_text(encoding='utf-8'))
    assert payload['name'] == 'Security Logic CI'
    steps = payload['jobs']['test']['steps']
    assert any(step.get('uses', '').startswith('actions/setup-node@') for step in steps)
    hidden_unicode_steps = [step for step in steps if step.get('name') == 'Check hidden Unicode and newline normalization']
    assert hidden_unicode_steps
    hidden_unicode_step = hidden_unicode_steps[0]
    assert '--verbose --report hidden_unicode_report.json' in hidden_unicode_step['run']
    assert 'hidden unicode report clean' in hidden_unicode_step['run']
    typescript_install_steps = [step for step in steps if step.get('name') == 'Install TypeScript toolchain']
    assert typescript_install_steps
    typescript_install_step = typescript_install_steps[0]
    assert 'npm install --no-save typescript' in typescript_install_step['run']
    typescript_test_steps = [step for step in steps if step.get('name') == 'Run emitted TypeScript schema compile/runtime tests']
    assert typescript_test_steps
    typescript_test_step = typescript_test_steps[0]
    assert typescript_test_step['env']['IPFS_SECURITY_REQUIRE_NODE_TOOLCHAIN'] == '1'
    assert 'npx tsc --version' in typescript_test_step['run']
    assert 'pytest tests/logic/security_models/crypto_exchange/test_typescript_schema_compiles.py -v --tb=short' in typescript_test_step['run']
    assert 'Skipping TypeScript compile test' not in typescript_test_step['run']
    upload_steps = [step for step in steps if step.get('uses', '').startswith('actions/upload-artifact@')]
    assert upload_steps
    assert any('hidden_unicode_report.json' in step.get('with', {}).get('path', '') for step in upload_steps)
    summary_steps = [step for step in steps if step.get('name') == 'Emit merge readiness summary']
    assert summary_steps
    assert 'security_logic_v1_summary.json' in summary_steps[0]['run']
