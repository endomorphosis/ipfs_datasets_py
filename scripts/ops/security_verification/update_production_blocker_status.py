#!/usr/bin/env python3
"""Guarded production blocker status updater for crypto_exchange.

PORTAL-CXTP-095 consumes the blocker evidence packets from PORTAL-CXTP-094
and the fail-closed production evidence intake report from PORTAL-CXTP-085. It
does not make production secure by itself; it produces a machine-readable status
update plan that keeps every production blocker closed unless the evidence
bundle was accepted and every packet-specific domain and claim check is
satisfied.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'production-blocker-status-update/v1'
TASK_ID = 'PORTAL-CXTP-095'
DEFAULT_PACKETS = Path('security_ir_artifacts/production/blocker-evidence-packets.json')
DEFAULT_EVIDENCE_REPORT = Path('security_ir_artifacts/production/evidence-bundle-report.json')
DEFAULT_BUNDLE = Path('security_ir_artifacts/production/evidence-bundle.json')
DEFAULT_OUT = Path('security_ir_artifacts/production/blocker-status-update-report.json')
POLICY_DOCUMENT = 'docs/security_verification/production_blocker_status_updater.md'

SECURITY_DECISION_BLOCKED = 'BLOCK_PRODUCTION_BLOCKER_STATUS_UPDATE'
SECURITY_DECISION_READY = 'PRODUCTION_BLOCKER_STATUS_UPDATE_CANDIDATES_READY'

BLOCKED_TASK_IDS = tuple(f'PORTAL-CXTP-{index:03d}' for index in range(77, 85))
REVIEWED_EVIDENCE_STATUSES = {'human_reviewed', 'trusted_fixture'}


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
    return digest.hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    """Return a stable CID-like content token for local evidence comparison."""

    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(canonical).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not path.is_file():
        return None, {'code': 'FILE_MISSING', 'path': path.as_posix()}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return None, {'code': 'JSON_PARSE_ERROR', 'path': path.as_posix(), 'error': str(exc)}
    if not isinstance(payload, dict):
        return None, {'code': 'JSON_NOT_OBJECT', 'path': path.as_posix()}
    return payload, None


def _bundle_items(bundle: Mapping[str, Any] | None, category: str) -> list[Mapping[str, Any]]:
    if not isinstance(bundle, Mapping):
        return []
    items = bundle.get(category)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def _domain_satisfied(
    *,
    request: Mapping[str, Any],
    bundle: Mapping[str, Any] | None,
) -> tuple[bool, list[dict[str, Any]]]:
    domain = str(request.get('domain') or '<missing>')
    category = str(request.get('evidence_bundle_category') or '')
    expected_owner = str(request.get('expected_owner') or '')
    accepted_statuses = set(request.get('accepted_review_statuses') or [])
    errors: list[dict[str, Any]] = []

    if not bundle:
        return False, [{'code': 'EVIDENCE_BUNDLE_UNAVAILABLE', 'domain': domain}]

    items = _bundle_items(bundle, category)
    if not items:
        return False, [
            {
                'code': 'PACKET_DOMAIN_CATEGORY_MISSING',
                'domain': domain,
                'category': category,
            }
        ]

    matched = False
    for item in items:
        owner = str(item.get('owner') or '')
        if category == 'owner_signoff':
            decision = str(item.get('decision') or '')
            status_ok = decision == 'approved'
            owner_ok = bool(owner)
            expected_ok = not expected_owner or owner == expected_owner or owner != 'REPLACE_WITH_NAMED_OWNER'
        else:
            review_status = str(item.get('review_status') or '')
            status_ok = review_status in REVIEWED_EVIDENCE_STATUSES and (
                not accepted_statuses or review_status in accepted_statuses
            )
            owner_ok = bool(owner)
            expected_ok = not expected_owner or owner == expected_owner

        if status_ok and owner_ok and expected_ok:
            matched = True
            break

    if not matched:
        errors.append(
            {
                'code': 'PACKET_DOMAIN_EVIDENCE_NOT_MATCHED',
                'domain': domain,
                'category': category,
                'expected_owner': expected_owner,
                'accepted_review_statuses': sorted(accepted_statuses),
                'item_count': len(items),
            }
        )
    return matched, errors


def _solver_outcomes_by_claim(bundle: Mapping[str, Any] | None) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for item in _bundle_items(bundle, 'solver_reports'):
        claim_id = item.get('claim_id')
        outcome = item.get('outcome')
        if isinstance(claim_id, str) and isinstance(outcome, str):
            outcomes[claim_id] = outcome
    return outcomes


def _packet_status_update(
    packet: Mapping[str, Any],
    *,
    evidence_report: Mapping[str, Any] | None,
    evidence_bundle: Mapping[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    packet_id = str(packet.get('id') or '<missing>')
    blocker_id = str(
        packet.get('source_packet_blocker_id')
        or packet.get('production_blocker_id')
        or packet_id
    )
    packet_blockers: list[dict[str, Any]] = []

    if not evidence_report:
        packet_blockers.append({'code': 'EVIDENCE_VALIDATION_REPORT_MISSING'})
    elif evidence_report.get('overall_status') != 'pass' or evidence_report.get('production_release_blocked'):
        packet_blockers.append(
            {
                'code': 'EVIDENCE_VALIDATION_REPORT_BLOCKED',
                'evidence_overall_status': evidence_report.get('overall_status'),
                'security_decision': evidence_report.get('security_decision'),
                'blocker_codes': [
                    blocker.get('code')
                    for blocker in evidence_report.get('blockers', [])
                    if isinstance(blocker, Mapping)
                ],
            }
        )

    domain_results: list[dict[str, Any]] = []
    for request in packet.get('evidence_requests', []):
        if not isinstance(request, Mapping):
            continue
        ok, errors = _domain_satisfied(request=request, bundle=evidence_bundle)
        domain_results.append(
            {
                'domain': request.get('domain'),
                'category': request.get('evidence_bundle_category'),
                'expected_owner': request.get('expected_owner'),
                'status': 'satisfied' if ok else 'blocked',
                'blockers': errors,
            }
        )
        packet_blockers.extend(errors)

    outcomes = _solver_outcomes_by_claim(evidence_bundle)
    claim_results: list[dict[str, Any]] = []
    for claim_id in packet.get('blocked_claim_ids', []):
        if not isinstance(claim_id, str):
            continue
        outcome = outcomes.get(claim_id)
        ok = outcome == 'prove'
        claim_results.append(
            {
                'claim_id': claim_id,
                'outcome': outcome,
                'status': 'proved' if ok else 'blocked',
            }
        )
        if not ok:
            packet_blockers.append(
                {
                    'code': 'PACKET_BLOCKED_CLAIM_NOT_PROVED',
                    'claim_id': claim_id,
                    'outcome': outcome,
                }
            )

    allowed = not packet_blockers
    return {
        'packet_id': packet_id,
        'blocker_id': blocker_id,
        'source_task_id': packet.get('source_task_id'),
        'current_status': packet.get('source_blocker_status'),
        'required_domains': packet.get('required_production_evidence_domains', []),
        'blocked_claim_ids': packet.get('blocked_claim_ids', []),
        'domain_results': domain_results,
        'claim_results': claim_results,
        'status_update_allowed': allowed,
        'proposed_status': 'evidence-accepted-pending-owner-close' if allowed else 'blocked_missing_production_evidence',
        'apply_mode': 'dry-run' if dry_run else 'report-only-apply-not-implemented',
        'production_release_effect': 'candidate-for-manual-unblock' if allowed else 'blocked-production',
        'may_mark_production_secure': False,
        'blockers': packet_blockers,
    }


def build_status_update_report(
    *,
    repo_root: Path | str | None = None,
    packets_path: Path | str = DEFAULT_PACKETS,
    evidence_report_path: Path | str = DEFAULT_EVIDENCE_REPORT,
    evidence_bundle_path: Path | str = DEFAULT_BUNDLE,
    dry_run: bool = True,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    packets_abs = Path(packets_path)
    report_abs = Path(evidence_report_path)
    bundle_abs = Path(evidence_bundle_path)
    if not packets_abs.is_absolute():
        packets_abs = root / packets_abs
    if not report_abs.is_absolute():
        report_abs = root / report_abs
    if not bundle_abs.is_absolute():
        bundle_abs = root / bundle_abs

    input_blockers: list[dict[str, Any]] = []
    packets, packet_error = _load_json(packets_abs)
    if packet_error:
        input_blockers.append({**packet_error, 'code': 'PACKETS_' + packet_error['code']})
    evidence_report, report_error = _load_json(report_abs)
    if report_error:
        input_blockers.append({**report_error, 'code': 'EVIDENCE_REPORT_' + report_error['code']})
    evidence_bundle, bundle_error = _load_json(bundle_abs)
    if bundle_error:
        input_blockers.append({**bundle_error, 'code': 'EVIDENCE_BUNDLE_' + bundle_error['code']})

    packet_items = packets.get('packets') if isinstance(packets, Mapping) else []
    if not isinstance(packet_items, list):
        packet_items = []
        input_blockers.append({'code': 'PACKETS_ARRAY_MISSING'})

    packet_updates = [
        _packet_status_update(
            packet,
            evidence_report=evidence_report,
            evidence_bundle=evidence_bundle,
            dry_run=dry_run,
        )
        for packet in packet_items
        if isinstance(packet, Mapping)
    ]

    allowed_count = sum(1 for update in packet_updates if update['status_update_allowed'])
    blocked_count = len(packet_updates) - allowed_count
    blocked = bool(input_blockers) or blocked_count > 0

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'repo_root': root.as_posix(),
        'mode': 'dry-run' if dry_run else 'report-only-apply-not-implemented',
        'overall_status': 'blocked' if blocked else 'ready',
        'production_release_blocked': blocked,
        'security_decision': SECURITY_DECISION_BLOCKED if blocked else SECURITY_DECISION_READY,
        'may_mark_production_secure': False,
        'blocked_task_ids_preserved': list(BLOCKED_TASK_IDS) if blocked else [],
        'inputs': {
            'packets': {
                'path': _relative(packets_abs, root),
                'exists': packets_abs.is_file(),
                'sha256': _sha256(packets_abs),
                'schema_version': packets.get('schema_version') if isinstance(packets, Mapping) else None,
                'artifact_cid': packets.get('artifact_cid') if isinstance(packets, Mapping) else None,
            },
            'evidence_report': {
                'path': _relative(report_abs, root),
                'exists': report_abs.is_file(),
                'sha256': _sha256(report_abs),
                'overall_status': evidence_report.get('overall_status') if isinstance(evidence_report, Mapping) else None,
                'security_decision': evidence_report.get('security_decision') if isinstance(evidence_report, Mapping) else None,
            },
            'evidence_bundle': {
                'path': _relative(bundle_abs, root),
                'exists': bundle_abs.is_file(),
                'sha256': _sha256(bundle_abs),
                'bundle_id': evidence_bundle.get('bundle_id') if isinstance(evidence_bundle, Mapping) else None,
            },
        },
        'summary': {
            'packet_count': len(packet_updates),
            'status_update_allowed_count': allowed_count,
            'status_update_blocked_count': blocked_count,
            'input_blocker_count': len(input_blockers),
            'packet_blocker_count': sum(len(update['blockers']) for update in packet_updates),
            'dry_run': dry_run,
        },
        'status_updates': packet_updates,
        'blockers': input_blockers,
        'operator_action': (
            'Keep PORTAL-CXTP-077 through PORTAL-CXTP-084 blocked until a production '
            'evidence bundle exists, validates with no blockers, and every packet reports '
            'status_update_allowed=true.'
            if blocked
            else (
                'Review the candidate status updates with the named release owners; this '
                'report is evidence for manual unblock work, not a declaration of security.'
            )
        ),
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def write_json(document: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Build a guarded production blocker status update report.'
    )
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root')
    parser.add_argument('--packets', default=DEFAULT_PACKETS.as_posix(), help='blocker evidence packets JSON')
    parser.add_argument(
        '--evidence-report',
        default=DEFAULT_EVIDENCE_REPORT.as_posix(),
        help='production evidence validation report JSON',
    )
    parser.add_argument(
        '--bundle',
        default=DEFAULT_BUNDLE.as_posix(),
        help='production evidence bundle JSON used for packet-domain checks',
    )
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='status update report path')
    parser.add_argument('--dry-run', action='store_true', help='write a dry-run report only')
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.repo_root)
    report = build_status_update_report(
        repo_root=root,
        packets_path=args.packets,
        evidence_report_path=args.evidence_report,
        evidence_bundle_path=args.bundle,
        dry_run=True if args.dry_run else True,
    )
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    write_json(report, out_path)
    print(
        json.dumps(
            {
                'report': _relative(out_path, root),
                'overall_status': report['overall_status'],
                'production_release_blocked': report['production_release_blocked'],
                'status_update_allowed_count': report['summary']['status_update_allowed_count'],
                'status_update_blocked_count': report['summary']['status_update_blocked_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
