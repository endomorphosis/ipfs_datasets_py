from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
ARTIFACT = ROOT / 'security_ir_artifacts/corpora/xaman-app/public-disclosure-routing.json'
DOCUMENT = ROOT / 'docs/security_verification/xaman_public_disclosure_routing.md'


def test_public_disclosure_routing_remains_non_authorizing() -> None:
    payload = json.loads(ARTIFACT.read_text(encoding='utf-8'))

    assert payload['task_id'] == 'PORTAL-CXTP-155'
    assert payload['authorization_granted'] is False
    assert payload['pinned_source_security_txt']['status'] == 'historical_route_expired_not_verified_current'
    assert payload['current_public_policy']['reported_contact'] == 'support@xaman.app'
    assert payload['required_before_sensitive_evidence_exchange']
    assert 'PORTAL-CXTP-153 remains blocked' in DOCUMENT.read_text(encoding='utf-8')
