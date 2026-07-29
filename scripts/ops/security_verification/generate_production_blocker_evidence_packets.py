#!/usr/bin/env python3
"""Generate production evidence packets for remaining crypto-exchange blockers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-production-blocker-evidence-packets/v1'
TASK_ID = 'PORTAL-CXTP-094'
DEFAULT_BRIDGE = Path('security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json')
DEFAULT_OUT = Path('security_ir_artifacts/production/blocker-evidence-packets.json')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(canonical).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _packet_for_task(task: Mapping[str, Any]) -> dict[str, Any]:
    required = list(task.get('required_evidence') or [])
    acceptance_files = list(task.get('acceptance_files') or [])
    return {
        'packet_id': f"production-evidence:{task['task_id'].lower()}",
        'task_id': task['task_id'],
        'title': task.get('title'),
        'status': 'missing_production_evidence',
        'release_acceptable': False,
        'owner': 'TBD',
        'freshness': {
            'required': True,
            'collected_at': None,
            'expires_at': None,
            'status': 'missing',
        },
        'human_review': {
            'required': True,
            'reviewed_by': None,
            'reviewed_at': None,
            'status': 'missing',
        },
        'source': {
            'required': True,
            'references': [],
            'status': 'missing',
        },
        'environment': {
            'required': task['task_id'] in {'PORTAL-CXTP-077', 'PORTAL-CXTP-079', 'PORTAL-CXTP-083', 'PORTAL-CXTP-084'},
            'references': [],
            'status': 'missing',
        },
        'runtime': {
            'required': task['task_id'] in {'PORTAL-CXTP-077', 'PORTAL-CXTP-083', 'PORTAL-CXTP-084'},
            'references': [],
            'status': 'missing',
        },
        'solver': {
            'required': task['task_id'] in {'PORTAL-CXTP-080', 'PORTAL-CXTP-081', 'PORTAL-CXTP-082', 'PORTAL-CXTP-084'},
            'references': [],
            'status': 'missing',
        },
        'required_evidence': required,
        'acceptance_files': acceptance_files,
        'related_xaman_blockers': list(task.get('related_xaman_blockers') or []),
        'unblocks': list(task.get('unblocks') or []),
        'missing_requirement_count': len(required) + len(acceptance_files),
        'blocking_codes': [
            'OWNER_MISSING',
            'FRESHNESS_MISSING',
            'HUMAN_REVIEW_MISSING',
            'PRODUCTION_REFERENCES_MISSING',
            'ACCEPTANCE_FILES_MISSING',
        ],
    }


def build_packets(
    *,
    repo_root: Path | str | None = None,
    bridge_path: Path | str = DEFAULT_BRIDGE,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    bridge = Path(bridge_path)
    if not bridge.is_absolute():
        bridge = root / bridge
    bridge_payload = _load_json(bridge)
    packets = [_packet_for_task(task) for task in bridge_payload['blocked_tasks']]
    payload = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at': _utc_now(),
        'source_bridge': {
            'path': bridge.relative_to(root).as_posix() if bridge.is_relative_to(root) else bridge.as_posix(),
            'sha256': _sha256(bridge),
            'artifact_cid': bridge_payload.get('artifact_cid'),
            'security_decision': bridge_payload.get('security_decision'),
        },
        'packet_count': len(packets),
        'release_acceptable_packet_count': sum(1 for packet in packets if packet['release_acceptable']),
        'missing_evidence_packet_count': sum(1 for packet in packets if packet['status'] == 'missing_production_evidence'),
        'packets': packets,
        'overall_status': 'blocked_missing_production_evidence',
        'security_decision': 'PRODUCTION_EVIDENCE_PACKETS_REQUIRE_REVIEWED_INPUTS',
        'production_release_blocked': True,
    }
    payload['artifact_cid'] = _artifact_cid(payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge', type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    payload = build_packets(bridge_path=args.bridge)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': args.out.as_posix(), 'packet_count': payload['packet_count']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
