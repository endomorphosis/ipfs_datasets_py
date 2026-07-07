from pathlib import Path

import pytest


def test_security_logic_workflow_yaml_parses_if_pyyaml_is_available() -> None:
    yaml = pytest.importorskip('yaml')
    workflow_path = Path(__file__).resolve().parents[4] / '.github' / 'workflows' / 'security-logic-ci.yml'
    payload = yaml.safe_load(workflow_path.read_text(encoding='utf-8'))
    assert payload['name'] == 'Security Logic CI'
    steps = payload['jobs']['test']['steps']
    assert any(step.get('uses', '').startswith('actions/setup-node@') for step in steps)
    typescript_install_step = next(step for step in steps if step.get('name') == 'Install focused TypeScript toolchain')
    assert 'npm install --global typescript' in typescript_install_step['run']
    typescript_test_step = next(step for step in steps if step.get('name') == 'Run emitted TypeScript schema compile test')
    assert 'pytest tests/logic/security_models/crypto_exchange/test_typescript_schema_compiles.py -v --tb=short' in typescript_test_step['run']
    assert 'Skipping TypeScript compile test' not in typescript_test_step['run']
