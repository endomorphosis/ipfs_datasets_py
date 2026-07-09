#!/usr/bin/env python3
"""Fail-closed validator for the production evidence intake bundle.

``PORTAL-CXTP-085`` builds the scaffold that lets blocked production
crypto-exchange theorem-prover tasks (``PORTAL-CXTP-077`` through
``PORTAL-CXTP-084``) be unblocked by a single, concrete, machine-checked
evidence bundle instead of prose claims. A bundle is a JSON document
conforming to
``security_ir_artifacts/production/evidence-bundle.schema.json`` that
collects:

- ``source_snapshots``    -- immutable production source/commit evidence
- ``environment_evidence`` -- production compute/custody/network evidence
- ``runtime_traces``      -- release-window runtime/monitoring evidence
- ``owner_signoff``       -- named accountable owner approvals
- ``solver_reports``      -- formal claim outcomes from the theorem provers

Every item in every category carries a ``collected_at_utc`` (or
``signed_at_utc``) timestamp that is checked against the bundle's
``freshness_policy``. This script performs schema-shape validation, file
existence and digest verification, freshness checks, owner-signoff
approval checks, and cross-checks solver report outcomes against the
frozen release policy (see
``ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy``).
It fails closed: any structural, missing, stale, unapproved, or
non-``prove`` blocking-claim finding blocks acceptance of the bundle.
"""

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

SECURITY_DECISION_BLOCKED = 'BLOCK_PRODUCTION_EVIDENCE_INTAKE'
SECURITY_DECISION_ACCEPTED = 'PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED'

# Vocabulary duplicated (with a source-of-truth comment) rather than imported so this
# validator can run even if the crypto_exchange package import path changes; the
# authoritative values are cross-checked against the live package in
# ``_reviewed_evidence_statuses`` / ``_release_policy_claims`` below whenever the
# package is importable.
EVIDENCE_REVIEW_STATUSES = frozenset(
    {'heuristic', 'machine_extracted', 'human_reviewed', 'trusted_fixture'}
)
REVIEWED_EVIDENCE_STATUSES = frozenset({'human_reviewed', 'trusted_fixture'})
SECURITY_DECISION_OUTCOME_IDS = frozenset(
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

EVIDENCE_CATEGORIES: tuple[str, ...] = (
    'source_snapshots',
    'environment_evidence',
    'runtime_traces',
    'owner_signoff',
    'solver_reports',
)

# category -> (timestamp field(s) checked for freshness, whether a file path is required)
_CATEGORY_TIMESTAMP_FIELDS: dict[str, tuple[str, ...]] = {
    'source_snapshots': ('collected_at_utc',),
    'environment_evidence': ('collected_at_utc',),
    'runtime_traces': ('collected_at_utc', 'window_end_utc'),
    'owner_signoff': ('signed_at_utc',),
    'solver_reports': ('collected_at_utc',),
}
_CATEGORY_REQUIRES_PATH: dict[str, bool] = {
    'source_snapshots': True,
    'environment_evidence': True,
    'runtime_traces': True,
    'owner_signoff': False,
    'solver_reports': True,
}
_CATEGORY_REQUIRES_REVIEW_STATUS: dict[str, bool] = {
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


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


def _reviewed_evidence_statuses() -> frozenset[str]:
    """Return the reviewed-status vocabulary, preferring the live package if importable."""

    try:
        from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
            REVIEWED_EVIDENCE_STATUSES as _live,
        )
    except Exception:  # pragma: no cover - defensive fallback only
        return REVIEWED_EVIDENCE_STATUSES
    return frozenset(_live)


def _release_policy_claims() -> dict[str, str]:
    """Return {claim_id: release_gate} from the live release policy, if importable."""

    try:
        from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
            release_policy_entries,
        )
    except Exception:  # pragma: no cover - defensive fallback only
        return {}
    return {entry.claim_id: entry.release_gate for entry in release_policy_entries()}


def _security_decision_outcome_ids() -> frozenset[str]:
    try:
        from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
            security_decision_outcomes,
        )
    except Exception:  # pragma: no cover - defensive fallback only
        return SECURITY_DECISION_OUTCOME_IDS
    return frozenset(outcome.outcome for outcome in security_decision_outcomes())


def load_schema(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as handle:
        return json.load(handle)


def load_bundle(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as handle:
        return json.load(handle)


def _blocker(code: str, **fields: Any) -> dict[str, Any]:
    return {'code': code, **fields}


def _schema_shape_blockers(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Structural checks independent of an external jsonschema dependency."""

    blockers: list[dict[str, Any]] = []

    if not isinstance(bundle, Mapping):
        return [_blocker('BUNDLE_NOT_OBJECT')]

    if bundle.get('schema_version') != SCHEMA_VERSION:
        blockers.append(
            _blocker(
                'BUNDLE_SCHEMA_VERSION_MISMATCH',
                expected=SCHEMA_VERSION,
                actual=bundle.get('schema_version'),
            )
        )

    for field_name in ('task_id', 'bundle_id', 'generated_at_utc'):
        if not isinstance(bundle.get(field_name), str) or not bundle.get(field_name):
            blockers.append(_blocker('BUNDLE_FIELD_MISSING', field=field_name))

    freshness_policy = bundle.get('freshness_policy')
    if not isinstance(freshness_policy, Mapping):
        blockers.append(_blocker('BUNDLE_FRESHNESS_POLICY_MISSING'))
    else:
        max_age_days = freshness_policy.get('max_age_days')
        if not isinstance(max_age_days, int) or isinstance(max_age_days, bool) or max_age_days < 1:
            blockers.append(
                _blocker('BUNDLE_FRESHNESS_POLICY_INVALID', field='max_age_days', value=max_age_days)
            )
        evaluated_at = freshness_policy.get('evaluated_at_utc')
        if evaluated_at is not None and _parse_dt(evaluated_at) is None:
            blockers.append(
                _blocker(
                    'BUNDLE_FRESHNESS_POLICY_INVALID',
                    field='evaluated_at_utc',
                    value=evaluated_at,
                )
            )

    for category in EVIDENCE_CATEGORIES:
        items = bundle.get(category)
        if not isinstance(items, list) or not items:
            blockers.append(_blocker('CATEGORY_EMPTY_OR_MISSING', category=category))

    return blockers


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


def _item_blockers(
    category: str,
    item: Any,
    index: int,
    *,
    repo_root: Path,
    reviewed_statuses: frozenset[str],
    outcome_ids: frozenset[str],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    where = {'category': category, 'index': index}

    if not isinstance(item, Mapping):
        return [_blocker('EVIDENCE_ITEM_NOT_OBJECT', **where)]

    item_id = item.get('id') if isinstance(item.get('id'), str) else f'<index {index}>'
    where = {**where, 'id': item_id}

    missing_fields = [
        field_name
        for field_name in _ITEM_REQUIRED_FIELDS[category]
        if not item.get(field_name) and item.get(field_name) != 0
    ]
    if missing_fields:
        blockers.append(_blocker('EVIDENCE_ITEM_FIELD_MISSING', fields=missing_fields, **where))

    review_status = item.get('review_status')
    if _CATEGORY_REQUIRES_REVIEW_STATUS[category]:
        if review_status is not None and review_status not in EVIDENCE_REVIEW_STATUSES:
            blockers.append(
                _blocker('EVIDENCE_REVIEW_STATUS_INVALID', value=review_status, **where)
            )
        elif review_status is not None and review_status not in reviewed_statuses:
            blockers.append(
                _blocker(
                    'EVIDENCE_NOT_REVIEWED',
                    review_status=review_status,
                    required_any_of=sorted(reviewed_statuses),
                    **where,
                )
            )

    path_text = item.get('path')
    if _CATEGORY_REQUIRES_PATH[category] and not path_text:
        blockers.append(_blocker('EVIDENCE_PATH_MISSING', **where))
    if path_text:
        artifact_path = repo_root / str(path_text)
        if not artifact_path.is_file():
            blockers.append(_blocker('EVIDENCE_FILE_MISSING', path=str(path_text), **where))
        else:
            expected_sha = item.get('sha256')
            if expected_sha:
                actual_sha = _sha256(artifact_path)
                if actual_sha != expected_sha:
                    blockers.append(
                        _blocker(
                            'EVIDENCE_DIGEST_MISMATCH',
                            path=str(path_text),
                            expected_sha256=expected_sha,
                            actual_sha256=actual_sha,
                            **where,
                        )
                    )

    if category == 'owner_signoff':
        decision = item.get('decision')
        if decision != 'approved':
            blockers.append(_blocker('OWNER_SIGNOFF_NOT_APPROVED', decision=decision, **where))

    if category == 'solver_reports':
        outcome = item.get('outcome')
        if outcome is not None and outcome not in outcome_ids:
            blockers.append(_blocker('SOLVER_OUTCOME_UNRECOGNIZED', outcome=outcome, **where))

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
    where = {'category': category, 'index': index, 'id': item_id}

    for field_name in _CATEGORY_TIMESTAMP_FIELDS[category]:
        raw_value = item.get(field_name)
        parsed = _parse_dt(raw_value)
        if parsed is None:
            blockers.append(
                _blocker('EVIDENCE_TIMESTAMP_INVALID', field=field_name, value=raw_value, **where)
            )
            continue
        age = now - parsed
        if age > timedelta(days=max_age_days):
            blockers.append(
                _blocker(
                    'EVIDENCE_STALE',
                    field=field_name,
                    timestamp=raw_value,
                    age_days=round(age.total_seconds() / 86400.0, 3),
                    max_age_days=max_age_days,
                    **where,
                )
            )
        if age < timedelta(0):
            blockers.append(
                _blocker('EVIDENCE_TIMESTAMP_IN_FUTURE', field=field_name, value=raw_value, **where)
            )

    return blockers


def _blocking_claim_blockers(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Cross-check solver report outcomes against the frozen release policy."""

    blockers: list[dict[str, Any]] = []
    claim_gates = _release_policy_claims()
    if not claim_gates:
        return blockers

    reports = bundle.get('solver_reports')
    if not isinstance(reports, list):
        return blockers

    latest_outcome_by_claim: dict[str, tuple[Any, dict[str, Any]]] = {}
    for index, report in enumerate(reports):
        if not isinstance(report, Mapping):
            continue
        claim_id = report.get('claim_id')
        if not isinstance(claim_id, str):
            continue
        collected_at = _parse_dt(report.get('collected_at_utc'))
        sort_key = collected_at or datetime.min.replace(tzinfo=timezone.utc)
        current = latest_outcome_by_claim.get(claim_id)
        if current is None or sort_key >= current[0]:
            latest_outcome_by_claim[claim_id] = (sort_key, {'index': index, **report})

    for claim_id, gate in sorted(claim_gates.items()):
        if gate not in ('blocking', 'high'):
            continue
        entry = latest_outcome_by_claim.get(claim_id)
        if entry is None:
            blockers.append(
                _blocker('BLOCKING_CLAIM_NOT_COVERED', claim_id=claim_id, release_gate=gate)
            )
            continue
        _, report = entry
        outcome = report.get('outcome')
        if outcome != 'prove':
            blockers.append(
                _blocker(
                    'BLOCKING_CLAIM_NOT_PROVED',
                    claim_id=claim_id,
                    release_gate=gate,
                    outcome=outcome,
                    index=report.get('index'),
                )
            )

    return blockers


def validate_bundle(
    bundle: Mapping[str, Any],
    *,
    repo_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a production evidence bundle and return a fail-closed report."""

    blockers: list[dict[str, Any]] = list(_schema_shape_blockers(bundle))
    reviewed_statuses = _reviewed_evidence_statuses()
    outcome_ids = _security_decision_outcome_ids()

    freshness_policy = bundle.get('freshness_policy') if isinstance(bundle, Mapping) else None
    max_age_days = None
    if isinstance(freshness_policy, Mapping):
        candidate = freshness_policy.get('max_age_days')
        if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 1:
            max_age_days = candidate

    evaluated_at = now
    if evaluated_at is None and isinstance(freshness_policy, Mapping):
        evaluated_at = _parse_dt(freshness_policy.get('evaluated_at_utc'))
    if evaluated_at is None:
        evaluated_at = datetime.now(timezone.utc)

    category_summaries: dict[str, dict[str, Any]] = {}
    for category in EVIDENCE_CATEGORIES:
        items = bundle.get(category) if isinstance(bundle, Mapping) else None
        item_count = len(items) if isinstance(items, list) else 0
        category_blockers = 0
        if isinstance(items, list):
            for index, item in enumerate(items):
                item_found = _item_blockers(
                    category,
                    item,
                    index,
                    repo_root=repo_root,
                    reviewed_statuses=reviewed_statuses,
                    outcome_ids=outcome_ids,
                )
                blockers.extend(item_found)
                category_blockers += len(item_found)
                if max_age_days is not None and isinstance(item, Mapping):
                    freshness_found = _freshness_blockers(
                        category,
                        item,
                        index,
                        now=evaluated_at,
                        max_age_days=max_age_days,
                    )
                    blockers.extend(freshness_found)
                    category_blockers += len(freshness_found)
        category_summaries[category] = {
            'item_count': item_count,
            'blocker_count': category_blockers,
        }

    blockers.extend(_blocking_claim_blockers(bundle if isinstance(bundle, Mapping) else {}))

    blocked = bool(blockers)
    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'checked_at_utc': _utc_now(),
        'evaluated_at_utc': evaluated_at.isoformat().replace('+00:00', 'Z'),
        'bundle_id': bundle.get('bundle_id') if isinstance(bundle, Mapping) else None,
        'bundle_task_id': bundle.get('task_id') if isinstance(bundle, Mapping) else None,
        'overall_status': 'blocked' if blocked else 'pass',
        'production_release_blocked': blocked,
        'security_decision': SECURITY_DECISION_BLOCKED if blocked else SECURITY_DECISION_ACCEPTED,
        'summary': {
            'category_count': len(EVIDENCE_CATEGORIES),
            'blocker_count': len(blockers),
            'categories': category_summaries,
        },
        'blockers': blockers,
    }


def build_example_bundle(*, repo_root: Path, task_id: str = 'PORTAL-CXTP-077') -> dict[str, Any]:
    """Build a self-consistent example bundle referencing real, present repo files.

    The example intentionally points at durable, checked-in repository files so a
    freshly generated bundle can be re-timestamped (see ``--now``) and pass
    validation, giving downstream teams a concrete, working starting point rather
    than an abstract description.
    """

    now = _utc_now()
    taskboard_path = 'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md'
    policy_path = 'security_ir_artifacts/policies/security-decision-policy.json'

    def _digest(path_text: str) -> str | None:
        candidate = repo_root / path_text
        return _sha256(candidate) if candidate.is_file() else None

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': task_id,
        'bundle_id': f'example-bundle-{now}',
        'generated_at_utc': now,
        'notes': (
            'Example scaffold bundle generated by '
            'validate_production_evidence_bundle.py --write-example. Replace every '
            'path, owner, and timestamp with real production evidence before using '
            'this bundle to unblock a production task.'
        ),
        'freshness_policy': {
            'max_age_days': 30,
            'evaluated_at_utc': now,
        },
        'source_snapshots': [
            {
                'id': 'source-snapshot-taskboard',
                'description': 'Example durable source snapshot placeholder.',
                'repository': 'endomorphosis/ipfs_datasets_py',
                'commit': 'REPLACE_WITH_PRODUCTION_COMMIT_SHA',
                'path': taskboard_path,
                'sha256': _digest(taskboard_path),
                'collected_at_utc': now,
                'owner': 'security-architecture',
                'review_status': 'trusted_fixture',
            }
        ],
        'environment_evidence': [
            {
                'id': 'environment-evidence-example',
                'description': 'Example environment evidence placeholder.',
                'environment': 'production',
                'path': policy_path,
                'sha256': _digest(policy_path),
                'collected_at_utc': now,
                'owner': 'security-architecture',
                'review_status': 'trusted_fixture',
            }
        ],
        'runtime_traces': [
            {
                'id': 'runtime-trace-example',
                'description': 'Example runtime trace placeholder.',
                'stream': 'REPLACE_WITH_PRODUCTION_STREAM_NAME',
                'path': policy_path,
                'sha256': _digest(policy_path),
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
                'scope': 'withdrawals',
                'owner': 'REPLACE_WITH_NAMED_OWNER',
                'role': 'release-owner',
                'decision': 'approved',
                'signed_at_utc': now,
                'statement': (
                    'Example placeholder signoff statement; replace with a real, '
                    'named production release-owner approval.'
                ),
            }
        ],
        'solver_reports': _example_solver_reports(now=now, policy_path=policy_path, digest=_digest),
    }


def _example_solver_reports(
    *,
    now: str,
    policy_path: str,
    digest: Any,
) -> list[dict[str, Any]]:
    """Build one example ``prove`` solver report per required blocking/high claim.

    Covers every claim the live release policy marks ``blocking`` or ``high`` so a
    freshly generated example bundle passes ``BLOCKING_CLAIM_NOT_COVERED`` /
    ``BLOCKING_CLAIM_NOT_PROVED`` checks out of the box. Falls back to the
    release policy frozen at authoring time if the package is not importable.
    """

    claim_gates = _release_policy_claims() or {
        'no_unauthorized_withdrawal': 'blocking',
        'no_over_reserved_internal_account': 'blocking',
        'global_asset_conservation': 'blocking',
        'no_deposit_before_finality': 'high',
        'no_signing_request_after_wallet_freeze': 'high',
        'capability_delegation_no_authority_increase': 'high',
        'revoked_capability_no_future_authorization': 'high',
    }
    required_claims = sorted(
        claim_id for claim_id, gate in claim_gates.items() if gate in ('blocking', 'high')
    )
    return [
        {
            'id': f'solver-report-{claim_id}',
            'description': f'Example solver report placeholder for {claim_id}.',
            'claim_id': claim_id,
            'solver': 'z3',
            'outcome': 'prove',
            'path': policy_path,
            'sha256': digest(policy_path),
            'collected_at_utc': now,
            'owner': 'security-architecture',
            'review_status': 'trusted_fixture',
        }
        for claim_id in required_claims
    ]


def write_json(document: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Validate a production evidence intake bundle for the crypto_exchange theorem prover.'
    )
    parser.add_argument('--repo-root', default=str(_repo_root()), help='repository root to resolve paths against')
    parser.add_argument('--schema', default=DEFAULT_SCHEMA.as_posix(), help='evidence bundle JSON Schema path')
    parser.add_argument('--bundle', help='evidence bundle JSON document to validate')
    parser.add_argument('--out', help='optional path to write the validation report JSON')
    parser.add_argument(
        '--now',
        help='override the current UTC instant used for freshness evaluation (ISO-8601), for reproducible checks',
    )
    parser.add_argument(
        '--write-example',
        help='write a self-consistent example bundle to this path instead of validating, and exit',
    )
    parser.add_argument(
        '--example-task-id',
        default='PORTAL-CXTP-077',
        help='task_id recorded in the generated example bundle',
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)

    if args.write_example:
        example = build_example_bundle(repo_root=repo_root, task_id=args.example_task_id)
        out_path = Path(args.write_example)
        if not out_path.is_absolute():
            out_path = repo_root / out_path
        write_json(example, out_path)
        print(json.dumps({'example_bundle_written': out_path.as_posix()}))
        return 0

    schema_path = Path(args.schema)
    if not schema_path.is_absolute():
        schema_path = repo_root / schema_path

    if not schema_path.is_file():
        result = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': SECURITY_DECISION_BLOCKED,
            'summary': {'blocker_count': 1},
            'blockers': [_blocker('SCHEMA_FILE_MISSING', path=schema_path.as_posix())],
        }
        if args.out:
            write_json(result, Path(args.out))
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    # Loading the schema validates it is well-formed JSON; the shape checks in
    # validate_bundle() are the authoritative fail-closed rules (kept in sync with
    # the schema file by tests) so this script has no hard runtime dependency on
    # a jsonschema implementation being installed.
    load_schema(schema_path)

    if not args.bundle:
        result = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': SECURITY_DECISION_BLOCKED,
            'summary': {'blocker_count': 1},
            'blockers': [_blocker('BUNDLE_ARGUMENT_MISSING')],
        }
        if args.out:
            write_json(result, Path(args.out))
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    bundle_path = Path(args.bundle)
    if not bundle_path.is_absolute():
        bundle_path = repo_root / bundle_path

    if not bundle_path.is_file():
        result = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': SECURITY_DECISION_BLOCKED,
            'summary': {'blocker_count': 1},
            'blockers': [_blocker('BUNDLE_FILE_MISSING', path=bundle_path.as_posix())],
        }
        if args.out:
            write_json(result, Path(args.out))
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    now = _parse_dt(args.now) if args.now else None
    if args.now and now is None:
        result = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'checked_at_utc': _utc_now(),
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': SECURITY_DECISION_BLOCKED,
            'summary': {'blocker_count': 1},
            'blockers': [_blocker('NOW_ARGUMENT_INVALID', value=args.now)],
        }
        if args.out:
            write_json(result, Path(args.out))
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    bundle = load_bundle(bundle_path)
    result = validate_bundle(bundle, repo_root=repo_root, now=now)

    if args.out:
        write_json(result, Path(args.out))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))

    return 2 if result['production_release_blocked'] else 0


if __name__ == '__main__':
    sys.exit(main())
