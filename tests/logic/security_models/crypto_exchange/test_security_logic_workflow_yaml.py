from pathlib import Path

import pytest


def test_security_logic_workflow_yaml_parses_if_pyyaml_is_available() -> None:
    yaml = pytest.importorskip('yaml')
    workflow_path = Path(__file__).resolve().parents[4] / '.github' / 'workflows' / 'security-logic-ci.yml'
    payload = yaml.safe_load(workflow_path.read_text(encoding='utf-8'))
    assert payload['name'] == 'Security Logic CI'
