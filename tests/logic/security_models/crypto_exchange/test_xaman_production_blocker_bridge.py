from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BRIDGE_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json'
PACKET_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/assurance-packet.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_to_production_blocker_bridge.md'


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


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_production_bridge_binds_assurance_packet() -> None:
    bridge = _json(BRIDGE_PATH)
    packet = _json(PACKET_PATH)

    assert bridge['task_id'] == 'PORTAL-CXTP-076'
    assert bridge['schema_version'] == 'xaman-production-blocker-bridge/v1'
    assert bridge['artifact_cid'].startswith('sha256:')
    assert bridge['xaman_assurance_packet']['path'] == (
        'security_ir_artifacts/corpora/xaman-app/assurance-packet.json'
    )
    assert bridge['xaman_assurance_packet']['artifact_cid'] == packet['artifact_cid']
    assert bridge['xaman_assurance_packet']['release_decision'] == 'reject_release'
    assert bridge['xaman_assurance_packet']['security_decision'] == 'BLOCK_XAMAN_RELEASE_ASSURANCE_PACKET'


def test_xaman_production_bridge_covers_all_blocked_production_tasks() -> None:
    bridge = _json(BRIDGE_PATH)

    assert bridge['blocked_task_count'] == len(EXPECTED_TASKS)
    assert set(bridge['task_ids']) == EXPECTED_TASKS
    assert {task['task_id'] for task in bridge['blocked_tasks']} == EXPECTED_TASKS
    assert bridge['overall_status'] == 'ready_blocker_bridge_generated'
    assert bridge['security_decision'] == 'PRODUCTION_BLOCKERS_MAPPED_RELEASE_REMAINS_BLOCKED'
    assert bridge['production_release_blocked'] is True

    for task in bridge['blocked_tasks']:
        assert task['current_status'] == 'blocked'
        assert task['related_xaman_blockers']
        assert task['required_evidence']
        assert task['acceptance_files']


def test_xaman_production_bridge_preserves_dependency_order() -> None:
    bridge = _json(BRIDGE_PATH)
    by_id = {task['task_id']: task for task in bridge['blocked_tasks']}

    assert 'PORTAL-CXTP-079' in by_id['PORTAL-CXTP-077']['unblocks']
    assert 'PORTAL-CXTP-079' in by_id['PORTAL-CXTP-078']['unblocks']
    assert 'PORTAL-CXTP-080' in by_id['PORTAL-CXTP-079']['unblocks']
    assert 'PORTAL-CXTP-081' in by_id['PORTAL-CXTP-080']['unblocks']
    assert 'PORTAL-CXTP-082' in by_id['PORTAL-CXTP-081']['unblocks']
    assert 'PORTAL-CXTP-084' in by_id['PORTAL-CXTP-082']['unblocks']
    assert 'PORTAL-CXTP-084' in by_id['PORTAL-CXTP-083']['unblocks']
    assert by_id['PORTAL-CXTP-084']['unblocks'] == []


def test_xaman_production_bridge_documentation_matches_policy() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-076' in doc
    assert 'PORTAL-CXTP-077' in doc
    assert 'PORTAL-CXTP-084' in doc
    assert 'PRODUCTION_BLOCKERS_MAPPED_RELEASE_REMAINS_BLOCKED' in doc
    assert 'Keep `PORTAL-CXTP-077` through `PORTAL-CXTP-084` blocked' in doc
