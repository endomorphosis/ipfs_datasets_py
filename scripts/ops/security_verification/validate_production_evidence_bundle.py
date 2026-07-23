#!/usr/bin/env python3
"""Fail-closed validator for production crypto_exchange evidence bundles."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


SCHEMA_VERSION = 'production-evidence-bundle/v1'
TASK_ID = 'PORTAL-CXTP-085'
DEFAULT_SCHEMA = Path('security_ir_artifacts/production/evidence-bundle.schema.json')
DEFAULT_BUNDLE = Path('security_ir_artifacts/production/evidence-bundle.json')
DEFAULT_OUT = Path('security_ir_artifacts/production/evidence-bundle-report.json')
SECURITY_DECISION_BLOCKED = 'BLOCK_PRODUCTION_EVIDENCE_INTAKE'
SECURITY_DECISION_ACCEPTED = 'PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED'
REVIEWED_EVIDENCE_STATUSES = frozenset({'human_reviewed', 'trusted_fixture'})
EVIDENCE_REVIEW_STATUSES = frozenset(
    {'heuristic', 'machine_extracted', 'human_reviewed', 'trusted_fixture'}
)
SECURITY_DECISION_OUTCOMES = frozenset(
    {
        'prove',
        'disprove',
        'unknown',
        'not-modeled',
        'stale-evidence',
        'missing-solver',
        'blocked-production',
    }
)
EVIDENCE_CATEGORIES = (
    'source_snapshots',
    'environment_evidence',
    'runtime_traces',
    'owner_signoff',
    'solver_reports',
)

_ITEM_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    'source_snapshots': ('id', 'path', 'collected_at_utc', 'owner', 'review_status', 'repository', 'commit'),
    'environment_evidence': ('id', 'path', 'collected_at_utc', 'owner', 'review_status', 'environment'),
    'runtime_traces': (
        'id',
        'path',
        'collected_at_utc',
        'owner',
        'review_status',
        'stream',
        'window_start_utc',
        'window_end_utc',
    ),
    'owner_signoff': ('id', 'scope', 'owner', 'role', 'decision', 'signed_at_utc', 'statement'),
    'solver_reports': (
        'id',
        'path',
        'collected_at_utc',
        'owner',
        'review_status',
        'claim_id',
        'solver',
        'outcome',
    ),
}
_CATEGORY_TIMESTAMP_FIELDS: dict[str, tuple[str, ...]] = {
    'source_snapshots': ('collected_at_utc',),
    'environment_evidence': ('collected_at_utc',),
    'runtime_traces': ('collected_at_utc', 'window_end_utc'),
    'owner_signoff': ('signed_at_utc',),
    'solver_reports': ('collected_at_utc',),
}
_CATEGORY_REQUIRES_PATH = {
    'source_snapshots': True,
    'environment_evidence': True,
    'runtime_traces': True,
    'owner_signoff': False,
    'solver_reports': True,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + '+00:00' if value.endswith('Z') else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _blocker(code: str, **fields: Any) -> dict[str, Any]:
    return {'code': code, **fields}


def _release_policy_claims() -> dict[str, str]:
    try:
        from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
            release_policy_entries,
        )
    except Exception:  # pragma: no cover - import fallback
        return {
            'no_unauthorized_withdrawal': 'blocking',
            'no_over_reserved_internal_account': 'blocking',
            'global_asset_conservation': 'blocking',
            'no_deposit_before_finality': 'high',
            'no_signing_request_after_wallet_freeze': 'high',
            'capability_delegation_no_authority_increase': 'high',
            'revoked_capability_no_future_authorization': 'high',
        }
    return {entry.claim_id: entry.release_gate for entry in release_policy_entries()}


def _schema_shape_blockers(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if bundle.get('schema_version') != SCHEMA_VERSION:
        blockers.append(
            _blocker(
                'BUNDLE_SCHEMA_VERSION_MISMATCH',
                expected=SCHEMA_VERSION,
                actual=bundle.get('schema_version'),
            )
        )
    for field in ('task_id', 'bundle_id', 'generated_at_utc'):
        if not isinstance(bundle.get(field), str) or not bundle.get(field):
            blockers.append(_blocker('BUNDLE_FIELD_MISSING', field=field))
    policy = bundle.get('freshness_policy')
    if not isinstance(policy, Mapping):
        blockers.append(_blocker('BUNDLE_FRESHNESS_POLICY_MISSING'))
    else:
        max_age_days = policy.get('max_age_days')
        if not isinstance(max_age_days, int) or isinstance(max_age_days, bool) or max_age_days < 1:
            blockers.append(_blocker('BUNDLE_FRESHNESS_POLICY_INVALID', field='max_age_days'))
        evaluated_at = policy.get('evaluated_at_utc')
        if evaluated_at is not None and _parse_dt(evaluated_at) is None:
            blockers.append(_blocker('BUNDLE_FRESHNESS_POLICY_INVALID', field='evaluated_at_utc'))
    for category in EVIDENCE_CATEGORIES:
        items = bundle.get(category)
        if not isinstance(items, list) or not items:
            blockers.append(_blocker('CATEGORY_EMPTY_OR_MISSING', category=category))
    return blockers


def _item_blockers(category: str, item: Any, index: int, *, repo_root: Path) -> list[dict[str, Any]]:
    if not isinstance(item, Mapping):
        return [_blocker('EVIDENCE_ITEM_NOT_OBJECT', category=category, index=index)]
    item_id = item.get('id') if isinstance(item.get('id'), str) else f'<index {index}>'
    where = {'category': category, 'index': index, 'id': item_id}
    blockers: list[dict[str, Any]] = []
    missing = [field for field in _ITEM_REQUIRED_FIELDS[category] if not item.get(field)]
    if missing:
        blockers.append(_blocker('EVIDENCE_ITEM_FIELD_MISSING', fields=missing, **where))

    review_status = item.get('review_status')
    if category != 'owner_signoff':
        if review_status not in EVIDENCE_REVIEW_STATUSES:
            blockers.append(_blocker('EVIDENCE_REVIEW_STATUS_INVALID', value=review_status, **where))
        elif review_status not in REVIEWED_EVIDENCE_STATUSES:
            blockers.append(
                _blocker(
                    'EVIDENCE_NOT_REVIEWED',
                    review_status=review_status,
                    required_any_of=sorted(REVIEWED_EVIDENCE_STATUSES),
                    **where,
                )
            )

    if _CATEGORY_REQUIRES_PATH[category]:
        path_text = item.get('path')
        if not path_text:
            blockers.append(_blocker('EVIDENCE_PATH_MISSING', **where))
        else:
            artifact = repo_root / str(path_text)
            if not artifact.is_file():
                blockers.append(_blocker('EVIDENCE_FILE_MISSING', path=str(path_text), **where))
            elif item.get('sha256') and _sha256(artifact) != item.get('sha256'):
                blockers.append(
                    _blocker(
                        'EVIDENCE_DIGEST_MISMATCH',
                        path=str(path_text),
                        expected_sha256=item.get('sha256'),
                        actual_sha256=_sha256(artifact),
                        **where,
                    )
                )

    if category == 'owner_signoff' and item.get('decision') != 'approved':
        blockers.append(_blocker('OWNER_SIGNOFF_NOT_APPROVED', decision=item.get('decision'), **where))
    if category == 'solver_reports' and item.get('outcome') not in SECURITY_DECISION_OUTCOMES:
        blockers.append(_blocker('SOLVER_OUTCOME_UNRECOGNIZED', outcome=item.get('outcome'), **where))
    if category == 'runtime_traces':
        start = _parse_dt(item.get('window_start_utc'))
        end = _parse_dt(item.get('window_end_utc'))
        if start is not None and end is not None and start > end:
            blockers.append(_blocker('RUNTIME_TRACE_WINDOW_INVERTED', **where))
    return blockers


def _freshness_blockers(
    category: str,
    item: Mapping[str, Any],
    index: int,
    *,
    now: datetime,
    max_age_days: int,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    item_id = item.get('id') if isinstance(item.get('id'), str) else f'<index {index}>'
    for field in _CATEGORY_TIMESTAMP_FIELDS[category]:
        parsed = _parse_dt(item.get(field))
        where = {'category': category, 'index': index, 'id': item_id, 'field': field}
        if parsed is None:
            blockers.append(_blocker('EVIDENCE_TIMESTAMP_INVALID', value=item.get(field), **where))
            continue
        age = now - parsed
        if age < timedelta(0):
            blockers.append(_blocker('EVIDENCE_TIMESTAMP_IN_FUTURE', value=item.get(field), **where))
        elif age > timedelta(days=max_age_days):
            blockers.append(
                _blocker(
                    'EVIDENCE_STALE',
                    timestamp=item.get(field),
                    age_days=round(age.total_seconds() / 86400.0, 3),
                    max_age_days=max_age_days,
                    **where,
                )
            )
    return blockers


def _blocking_claim_blockers(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    reports = bundle.get('solver_reports')
    if not isinstance(reports, list):
        return []
    outcomes = {
        item.get('claim_id'): item.get('outcome')
        for item in reports
        if isinstance(item, Mapping) and isinstance(item.get('claim_id'), str)
    }
    blockers: list[dict[str, Any]] = []
    for claim_id, gate in sorted(_release_policy_claims().items()):
        if gate not in ('blocking', 'high'):
            continue
        outcome = outcomes.get(claim_id)
        if outcome is None:
            blockers.append(_blocker('BLOCKING_CLAIM_NOT_COVERED', claim_id=claim_id, release_gate=gate))
        elif outcome != 'prove':
            blockers.append(
                _blocker(
                    'BLOCKING_CLAIM_NOT_PROVED',
                    claim_id=claim_id,
                    release_gate=gate,
                    outcome=outcome,
                )
            )
    return blockers


def validate_bundle(
    bundle: Mapping[str, Any],
    *,
    repo_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    blockers = _schema_shape_blockers(bundle)
    policy = bundle.get('freshness_policy') if isinstance(bundle, Mapping) else None
    max_age_days = policy.get('max_age_days') if isinstance(policy, Mapping) else None
    evaluated_at = now
    if evaluated_at is None and isinstance(policy, Mapping):
        evaluated_at = _parse_dt(policy.get('evaluated_at_utc'))
    if evaluated_at is None:
        evaluated_at = datetime.now(timezone.utc)

    categories: dict[str, dict[str, Any]] = {}
    for category in EVIDENCE_CATEGORIES:
        items = bundle.get(category)
        item_count = len(items) if isinstance(items, list) else 0
        before = len(blockers)
        if isinstance(items, list):
            for index, item in enumerate(items):
                blockers.extend(_item_blockers(category, item, index, repo_root=repo_root))
                if isinstance(item, Mapping) and isinstance(max_age_days, int) and max_age_days >= 1:
                    blockers.extend(
                        _freshness_blockers(
                            category,
                            item,
                            index,
                            now=evaluated_at,
                            max_age_days=max_age_days,
                        )
                    )
        categories[category] = {
            'item_count': item_count,
            'blocker_count': len(blockers) - before,
        }
    blockers.extend(_blocking_claim_blockers(bundle))
    blocked = bool(blockers)
    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'checked_at_utc': _utc_now(),
        'evaluated_at_utc': evaluated_at.isoformat().replace('+00:00', 'Z'),
        'bundle_id': bundle.get('bundle_id'),
        'bundle_task_id': bundle.get('task_id'),
        'overall_status': 'blocked' if blocked else 'pass',
        'production_release_blocked': blocked,
        'security_decision': SECURITY_DECISION_BLOCKED if blocked else SECURITY_DECISION_ACCEPTED,
        'summary': {
            'category_count': len(EVIDENCE_CATEGORIES),
            'blocker_count': len(blockers),
            'categories': categories,
        },
        'blockers': blockers,
    }


def build_example_bundle(*, repo_root: Path, task_id: str = 'PORTAL-CXTP-077') -> dict[str, Any]:
    now = _utc_now()
    policy_path = 'security_ir_artifacts/policies/security-decision-policy.json'
    taskboard_path = 'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md'

    def digest(path_text: str) -> str | None:
        candidate = repo_root / path_text
        return _sha256(candidate) if candidate.is_file() else None

    solver_reports = [
        {
            'id': f'solver-report-{claim_id}',
            'description': f'Example proof report placeholder for {claim_id}.',
            'claim_id': claim_id,
            'solver': 'z3',
            'outcome': 'prove',
            'path': policy_path,
            'sha256': digest(policy_path),
            'collected_at_utc': now,
            'owner': 'security-architecture',
            'review_status': 'trusted_fixture',
        }
        for claim_id, gate in sorted(_release_policy_claims().items())
        if gate in ('blocking', 'high')
    ]
    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': task_id,
        'bundle_id': f'example-bundle-{now}',
        'generated_at_utc': now,
        'freshness_policy': {'max_age_days': 30, 'evaluated_at_utc': now},
        'source_snapshots': [
            {
                'id': 'source-snapshot-example',
                'repository': 'REPLACE_WITH_PRODUCTION_REPOSITORY',
                'commit': 'REPLACE_WITH_PRODUCTION_COMMIT',
                'path': taskboard_path,
                'sha256': digest(taskboard_path),
                'collected_at_utc': now,
                'owner': 'security-architecture',
                'review_status': 'trusted_fixture',
            }
        ],
        'environment_evidence': [
            {
                'id': 'environment-evidence-example',
                'environment': 'production',
                'path': policy_path,
                'sha256': digest(policy_path),
                'collected_at_utc': now,
                'owner': 'security-architecture',
                'review_status': 'trusted_fixture',
            }
        ],
        'runtime_traces': [
            {
                'id': 'runtime-trace-example',
                'stream': 'REPLACE_WITH_PRODUCTION_STREAM',
                'path': policy_path,
                'sha256': digest(policy_path),
                'collected_at_utc': now,
                'window_start_utc': now,
                'window_end_utc': now,
                'owner': 'security-architecture',
                'review_status': 'trusted_fixture',
            }
        ],
        'owner_signoff': [
            {
                'id': 'owner-signoff-example',
                'scope': 'production-release-boundary',
                'owner': 'named-security-release-owner',
                'role': 'release-owner',
                'decision': 'approved',
                'signed_at_utc': now,
                'statement': 'Example placeholder signoff; replace with named production owner approval.',
            }
        ],
        'solver_reports': solver_reports,
    }


def write_json(document: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate production evidence bundle.')
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root')
    parser.add_argument('--schema', default=DEFAULT_SCHEMA.as_posix(), help='schema path')
    parser.add_argument('--bundle', default=DEFAULT_BUNDLE.as_posix(), help='bundle path')
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='report output path')
    parser.add_argument('--now', help='override freshness evaluation instant')
    parser.add_argument('--write-example', help='write an example bundle and exit')
    parser.add_argument('--example-task-id', default='PORTAL-CXTP-077', help='task id for example bundle')
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.repo_root)
    schema_path = Path(args.schema)
    bundle_path = Path(args.bundle)
    out_path = Path(args.out)
    if not schema_path.is_absolute():
        schema_path = root / schema_path
    if not bundle_path.is_absolute():
        bundle_path = root / bundle_path
    if not out_path.is_absolute():
        out_path = root / out_path

    if args.write_example:
        example_path = Path(args.write_example)
        if not example_path.is_absolute():
            example_path = root / example_path
        write_json(build_example_bundle(repo_root=root, task_id=args.example_task_id), example_path)
        print(json.dumps({'example_bundle_written': example_path.as_posix()}, sort_keys=True))
        return 0

    if not schema_path.is_file():
        report = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': SECURITY_DECISION_BLOCKED,
            'summary': {'blocker_count': 1},
            'blockers': [_blocker('SCHEMA_FILE_MISSING', path=schema_path.as_posix())],
        }
        write_json(report, out_path)
        print(json.dumps({'report': out_path.as_posix(), 'overall_status': 'blocked'}, sort_keys=True))
        return 2

    if not bundle_path.is_file():
        report = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': SECURITY_DECISION_BLOCKED,
            'summary': {'blocker_count': 1},
            'blockers': [_blocker('BUNDLE_FILE_MISSING', path=bundle_path.as_posix())],
        }
        write_json(report, out_path)
        print(json.dumps({'report': out_path.as_posix(), 'overall_status': 'blocked'}, sort_keys=True))
        return 2

    now = _parse_dt(args.now) if args.now else None
    if args.now and now is None:
        report = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': SECURITY_DECISION_BLOCKED,
            'summary': {'blocker_count': 1},
            'blockers': [_blocker('NOW_ARGUMENT_INVALID', value=args.now)],
        }
        write_json(report, out_path)
        return 2

    with bundle_path.open('r', encoding='utf-8') as handle:
        bundle = json.load(handle)
    report = validate_bundle(bundle, repo_root=root, now=now)
    write_json(report, out_path)
    print(
        json.dumps(
            {
                'report': out_path.as_posix(),
                'overall_status': report['overall_status'],
                'production_release_blocked': report['production_release_blocked'],
            },
            sort_keys=True,
        )
    )
    return 2 if report['production_release_blocked'] else 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
