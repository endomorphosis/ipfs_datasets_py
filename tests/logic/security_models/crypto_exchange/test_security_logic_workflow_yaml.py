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
    typescript_compile_steps = [step for step in steps if step.get('name') == 'Run emitted TypeScript schema compile tests']
    assert typescript_compile_steps
    typescript_compile_step = typescript_compile_steps[0]
    assert typescript_compile_step['env']['IPFS_SECURITY_REQUIRE_NODE_TOOLCHAIN'] == '1'
    assert 'npx tsc --version' in typescript_compile_step['run']
    assert 'test_typescript_schema_compiles_when_tsc_is_available' in typescript_compile_step['run']
    assert 'test_typescript_schema_cli_emitter_outputs_strict_compilable_module' in typescript_compile_step['run']
    typescript_runtime_steps = [step for step in steps if step.get('name') == 'Run emitted TypeScript runtime verifier tests']
    assert typescript_runtime_steps
    typescript_runtime_step = typescript_runtime_steps[0]
    assert typescript_runtime_step['env']['IPFS_SECURITY_REQUIRE_NODE_TOOLCHAIN'] == '1'
    assert 'test_typescript_runtime_verifier_rejects_bad_receipts_and_accepts_valid_fixture' in typescript_runtime_step['run']
    upload_steps = [step for step in steps if step.get('uses', '').startswith('actions/upload-artifact@')]
    assert upload_steps
    assert any('hidden_unicode_report.json' in step.get('with', {}).get('path', '') for step in upload_steps)
    summary_steps = [step for step in steps if step.get('name') == 'Emit merge readiness summary']
    assert summary_steps
    assert 'security_logic_v1_summary.json' in summary_steps[0]['run']
    assert 'steps.typescript_compile.outcome' in summary_steps[0]['run']
    assert 'steps.typescript_runtime.outcome' in summary_steps[0]['run']
