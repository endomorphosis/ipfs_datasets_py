from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/generate_production_blocker_evidence_packets.py'
PACKETS_PATH = ROOT / 'security_ir_artifacts/production/blocker-evidence-packets.json'
BRIDGE_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json'
DOC_PATH = ROOT / 'docs/security_verification/production_blocker_evidence_packets.md'


EXPECTED_TASKS = {
    'PORTAL-CXTP-077',
    'PORTAL-CXTP-078',
    'PORTAL-CXTP-079',
    'PORTAL-CXTP-080',
    'PORTAL-CXTP-081',
    'PORTAL-CXTP-082',
    'PORTAL-CXTP-083',
    'PORTAL-CXTP-084',
}


def _module():
    spec = importlib.util.spec_from_file_location('generate_production_blocker_evidence_packets', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_production_blocker_packet_generator_builds_one_packet_per_blocker() -> None:
    module = _module()

    payload = module.build_packets(repo_root=ROOT, bridge_path=BRIDGE_PATH)

    assert payload['task_id'] == 'PORTAL-CXTP-094'
    assert payload['schema_version'] == 'crypto-exchange-production-blocker-evidence-packets/v1'
    assert payload['packet_count'] == len(EXPECTED_TASKS)
    assert payload['missing_evidence_packet_count'] == len(EXPECTED_TASKS)
    assert payload['release_acceptable_packet_count'] == 0
    assert {packet['task_id'] for packet in payload['packets']} == EXPECTED_TASKS
    assert payload['production_release_blocked'] is True
    assert payload['artifact_cid'].startswith('sha256:')


def test_production_blocker_packet_cli_writes_output(tmp_path: Path) -> None:
    module = _module()
    out = tmp_path / 'blocker-evidence-packets.json'

    exit_code = module.main(['--out', str(out)])

    assert exit_code == 0
    payload = _json(out)
    assert payload['packet_count'] == len(EXPECTED_TASKS)


def test_persisted_production_blocker_packets_are_fail_closed() -> None:
    payload = _json(PACKETS_PATH)

    assert payload['task_id'] == 'PORTAL-CXTP-094'
    assert payload['overall_status'] == 'blocked_missing_production_evidence'
    assert payload['security_decision'] == 'PRODUCTION_EVIDENCE_PACKETS_REQUIRE_REVIEWED_INPUTS'
    assert payload['production_release_blocked'] is True
    assert payload['release_acceptable_packet_count'] == 0
    for packet in payload['packets']:
        assert packet['status'] == 'missing_production_evidence'
        assert packet['release_acceptable'] is False
        assert packet['owner'] == 'TBD'
        assert packet['freshness']['status'] == 'missing'
        assert packet['human_review']['status'] == 'missing'
        assert packet['required_evidence']
        assert packet['acceptance_files']
        assert 'ACCEPTANCE_FILES_MISSING' in packet['blocking_codes']


def test_production_blocker_packets_include_required_evidence_domains() -> None:
    payload = _json(PACKETS_PATH)
    by_id = {packet['task_id']: packet for packet in payload['packets']}

    assert by_id['PORTAL-CXTP-077']['environment']['required'] is True
    assert by_id['PORTAL-CXTP-078']['source']['required'] is True
    assert by_id['PORTAL-CXTP-081']['solver']['required'] is True
    assert by_id['PORTAL-CXTP-083']['runtime']['required'] is True
    assert by_id['PORTAL-CXTP-084']['environment']['required'] is True
    assert by_id['PORTAL-CXTP-084']['runtime']['required'] is True
    assert by_id['PORTAL-CXTP-084']['solver']['required'] is True


def test_production_blocker_packet_documentation_describes_release_policy() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-094' in doc
    assert 'release_acceptable: false' in doc
    assert 'cannot become release-acceptable merely because it exists' in doc
    assert 'assigned owner' in doc
