#!/usr/bin/env python3
"""Fail-closed taskboard preflight for crypto-exchange security verification."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-taskboard-preflight/v1'
TASK_ID = 'PORTAL-CXTP-087'

DEFAULT_TASKBOARD = Path('docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md')
DEFAULT_RETENTION_BASELINE = Path('security_ir_artifacts/recovery/artifact-retention-baseline.json')
DEFAULT_RELEASE_POLICY = Path('security_ir_artifacts/policies/security-decision-policy.json')

SECURITY_DECISION_BLOCKED = 'BLOCK_CRYPTO_EXCHANGE_TASKBOARD_PREFLIGHT'
SECURITY_DECISION_PASSED = 'CRYPTO_EXCHANGE_TASKBOARD_PREFLIGHT_PASS'

VALID_STATUSES = frozenset({'todo', 'completed', 'blocked'})
NON_SECURE_RELEASE_OUTCOMES = frozenset(
    {
        'disprove',
        'unknown',
        'not-modeled',
        'stale-evidence',
        'missing-solver',
        'blocked-production',
    }
)
TRUE_VALUES = frozenset({'1', 'true', 'yes', 'y', 'pass', 'passed', 'allowed', 'acceptable', 'accepted'})
REQUIRED_TASK_FIELDS = (
    'status',
    'completion',
    'priority',
    'track',
    'depends_on',
    'outputs',
    'validation',
    'acceptance',
)
RETENTION_GROUPS_CHECKED = frozenset(
    {
        'taskboard',
        'source_files',
        'retention_controls',
        'plans_and_release_policy',
        'solver_artifacts',
        'assurance_packets',
        'xaman_manifests',
        'model_facts',
        'recovery_artifacts',
    }
)

TASK_HEADER_RE = re.compile(r'^## (?P<task_id>PORTAL-CXTP-\d+) (?P<title>.+?)\s*$', re.MULTILINE)
METADATA_RE = re.compile(r'^- (?P<key>[A-Za-z][A-Za-z0-9 _/-]*):(?P<value>.*)$')


@dataclass(frozen=True)
class TaskboardTask:
    task_id: str
    title: str
    line: int
    body: str
    metadata: dict[str, str]

    @property
    def status(self) -> str:
        return self.metadata.get('status', '').strip().lower()

    @property
    def outputs(self) -> list[str]:
        return _split_path_list(self.metadata.get('outputs', ''))

    @property
    def depends_on(self) -> list[str]:
        value = self.metadata.get('depends_on', '')
        return [item for item in _split_csv(value) if item.startswith('PORTAL-CXTP-')]

    @property
    def is_production_task(self) -> bool:
        haystack = ' '.join([self.title, self.body]).lower()
        if 'production' in haystack:
            return True
        return any('/production/' in path or path.startswith('security_ir_artifacts/production/') for path in self.outputs)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize_key(key: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', key.strip().lower()).strip('_')


def _split_csv(value: str) -> list[str]:
    return [item.strip().strip('`') for item in value.split(',') if item.strip()]


def _split_path_list(value: str) -> list[str]:
    paths: list[str] = []
    for item in _split_csv(value):
        candidate = item.strip().strip('`').rstrip('.')
        if not candidate or candidate.startswith(('http://', 'https://')):
            continue
        paths.append(candidate)
    return paths


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception as exc:  # pragma: no cover - exact decoder text can vary
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, 'JSON document is not an object'
    return payload, None


def _blocker(code: str, **fields: Any) -> dict[str, Any]:
    return {'code': code, **fields}


def parse_taskboard(text: str) -> list[TaskboardTask]:
    """Parse supervisor task entries from the taskboard markdown."""

    matches = list(TASK_HEADER_RE.finditer(text))
    tasks: list[TaskboardTask] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        metadata: dict[str, str] = {}
        for raw_line in body.splitlines():
            parsed = METADATA_RE.match(raw_line.strip())
            if not parsed:
                continue
            metadata[_normalize_key(parsed.group('key'))] = parsed.group('value').strip()
        tasks.append(
            TaskboardTask(
                task_id=match.group('task_id'),
                title=match.group('title').strip(),
                line=text.count('\n', 0, match.start()) + 1,
                body=body,
                metadata=metadata,
            )
        )
    return tasks


def _read_taskboard(path: Path) -> tuple[list[TaskboardTask], list[dict[str, Any]]]:
    if not path.is_file():
        return [], [_blocker('TASKBOARD_FILE_MISSING', path=path.as_posix())]
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError as exc:
        return [], [_blocker('TASKBOARD_NOT_UTF8', path=path.as_posix(), error=str(exc))]
    tasks = parse_taskboard(text)
    if not tasks:
        return [], [_blocker('TASKBOARD_NO_PARSEABLE_TASKS', path=path.as_posix())]
    return tasks, []


def _retention_presence_blockers(baseline_path: Path, repo_root: Path) -> list[dict[str, Any]]:
    if not baseline_path.is_file():
        return [_blocker('RETENTION_BASELINE_MISSING', path=_relative(baseline_path, repo_root))]

    baseline, error = _load_json(baseline_path)
    if baseline is None:
        return [
            _blocker(
                'RETENTION_BASELINE_MALFORMED',
                path=_relative(baseline_path, repo_root),
                error=error,
            )
        ]

    blockers: list[dict[str, Any]] = []
    if baseline.get('schema_version') != 'crypto-exchange-artifact-retention/v1':
        blockers.append(
            _blocker(
                'RETENTION_BASELINE_SCHEMA_MISMATCH',
                expected='crypto-exchange-artifact-retention/v1',
                actual=baseline.get('schema_version'),
            )
        )
    if baseline.get('task_id') != 'PORTAL-CXTP-057':
        blockers.append(
            _blocker('RETENTION_BASELINE_TASK_MISMATCH', expected='PORTAL-CXTP-057', actual=baseline.get('task_id'))
        )

    groups = baseline.get('groups')
    if not isinstance(groups, list) or not groups:
        return [*blockers, _blocker('RETENTION_BASELINE_GROUPS_MISSING')]

    for group in groups:
        if not isinstance(group, Mapping):
            blockers.append(_blocker('RETENTION_BASELINE_GROUP_MALFORMED', group=group))
            continue
        group_name = str(group.get('name') or '<unnamed>')
        if group_name not in RETENTION_GROUPS_CHECKED:
            continue
        entries = group.get('entries')
        if not isinstance(entries, list) or not entries:
            blockers.append(_blocker('RETENTION_BASELINE_GROUP_EMPTY', group=group_name))
            continue
        missing: list[str] = []
        malformed = 0
        for entry in entries:
            if not isinstance(entry, Mapping) or not entry.get('path'):
                malformed += 1
                continue
            path_text = str(entry['path'])
            if not (repo_root / path_text).is_file():
                missing.append(path_text)
        if malformed:
            blockers.append(
                _blocker('RETENTION_BASELINE_ENTRY_MALFORMED', group=group_name, count=malformed)
            )
        if missing:
            blockers.append(
                _blocker(
                    'RETAINED_ARTIFACT_MISSING',
                    group=group_name,
                    count=len(missing),
                    paths=missing,
                )
            )
    return blockers


def _task_metadata_blockers(tasks: Sequence[TaskboardTask], repo_root: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    seen: set[str] = set()

    for task in tasks:
        if task.task_id in seen:
            blockers.append(_blocker('TASKBOARD_DUPLICATE_TASK_ID', task_id=task.task_id, line=task.line))
        seen.add(task.task_id)

        missing_fields = [field for field in REQUIRED_TASK_FIELDS if field not in task.metadata]
        if missing_fields:
            blockers.append(
                _blocker(
                    'TASK_METADATA_FIELD_MISSING',
                    task_id=task.task_id,
                    line=task.line,
                    fields=missing_fields,
                )
            )

        if task.status not in VALID_STATUSES:
            blockers.append(
                _blocker(
                    'TASK_STATUS_UNRECOGNIZED',
                    task_id=task.task_id,
                    line=task.line,
                    status=task.metadata.get('status'),
                    allowed=sorted(VALID_STATUSES),
                )
            )

        if task.status == 'blocked' and not task.metadata.get('blocked_reason'):
            blockers.append(_blocker('BLOCKED_TASK_MISSING_REASON', task_id=task.task_id, line=task.line))

        if task.status == 'completed' and task.metadata.get('blocked_reason'):
            blockers.append(_blocker('COMPLETED_TASK_HAS_BLOCKED_REASON', task_id=task.task_id, line=task.line))

        if task.status == 'completed':
            missing_outputs = [
                path
                for path in task.outputs
                if not (repo_root / path).is_file()
            ]
            if missing_outputs:
                blockers.append(
                    _blocker(
                        'COMPLETED_TASK_OUTPUT_MISSING',
                        task_id=task.task_id,
                        line=task.line,
                        count=len(missing_outputs),
                        paths=missing_outputs,
                    )
                )

        if task.status == 'blocked' and task.is_production_task:
            blockers.extend(_blocked_production_release_acceptance_blockers(task))

    return blockers


def _blocked_production_release_acceptance_blockers(task: TaskboardTask) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for key, raw_value in task.metadata.items():
        value = raw_value.strip().lower()
        if key in {'release_acceptable', 'production_release_acceptable', 'release_ready'} and value in TRUE_VALUES:
            blockers.append(
                _blocker(
                    'PRODUCTION_BLOCKER_MARKED_RELEASE_ACCEPTABLE',
                    task_id=task.task_id,
                    line=task.line,
                    field=key,
                    value=raw_value,
                )
            )
        if 'release-acceptable' in value or 'eligible-for-acceptance' in value:
            blockers.append(
                _blocker(
                    'PRODUCTION_BLOCKER_TEXT_MARKS_RELEASE_ACCEPTABLE',
                    task_id=task.task_id,
                    line=task.line,
                    field=key,
                    value=raw_value,
                )
            )
    return blockers


def _release_policy_blockers(policy_path: Path, repo_root: Path) -> list[dict[str, Any]]:
    if not policy_path.is_file():
        return [_blocker('RELEASE_POLICY_MISSING', path=_relative(policy_path, repo_root))]
    policy, error = _load_json(policy_path)
    if policy is None:
        return [
            _blocker(
                'RELEASE_POLICY_MALFORMED',
                path=_relative(policy_path, repo_root),
                error=error,
            )
        ]

    blockers: list[dict[str, Any]] = []
    default_rule = str(policy.get('default_consumer_rule') or '').lower()
    if 'only outcome prove' not in default_rule or 'non-proved' not in default_rule:
        blockers.append(_blocker('RELEASE_POLICY_DEFAULT_RULE_WEAK', default_consumer_rule=policy.get('default_consumer_rule')))

    outcomes = policy.get('outcomes')
    if not isinstance(outcomes, list) or not outcomes:
        return [*blockers, _blocker('RELEASE_POLICY_OUTCOMES_MISSING')]

    outcomes_by_id: dict[str, Mapping[str, Any]] = {}
    for outcome in outcomes:
        if isinstance(outcome, Mapping) and isinstance(outcome.get('outcome'), str):
            outcomes_by_id[outcome['outcome']] = outcome
        else:
            blockers.append(_blocker('RELEASE_POLICY_OUTCOME_MALFORMED', outcome=outcome))

    prove = outcomes_by_id.get('prove')
    if prove is None:
        blockers.append(_blocker('RELEASE_POLICY_PROVE_OUTCOME_MISSING'))
    elif prove.get('secure_for_blocking_claims') is not True:
        blockers.append(_blocker('RELEASE_POLICY_PROVE_NOT_SECURE', outcome='prove'))

    for outcome_id in sorted(NON_SECURE_RELEASE_OUTCOMES):
        outcome = outcomes_by_id.get(outcome_id)
        if outcome is None:
            blockers.append(_blocker('RELEASE_POLICY_NON_SECURE_OUTCOME_MISSING', outcome=outcome_id))
            continue
        if outcome.get('secure_for_blocking_claims') is not False:
            blockers.append(
                _blocker(
                    'RELEASE_POLICY_NON_PROVE_OUTCOME_MARKED_SECURE',
                    outcome=outcome_id,
                    secure_for_blocking_claims=outcome.get('secure_for_blocking_claims'),
                )
            )
        if outcome.get('production_release_effect') != 'blocked-production':
            blockers.append(
                _blocker(
                    'RELEASE_POLICY_NON_PROVE_OUTCOME_NOT_BLOCKING',
                    outcome=outcome_id,
                    production_release_effect=outcome.get('production_release_effect'),
                )
            )

    proof_boundary = policy.get('proof_boundary') if isinstance(policy.get('proof_boundary'), Mapping) else {}
    listed_non_secure = set(proof_boundary.get('non_secure_blocking_outcomes') or [])
    missing_non_secure = sorted(NON_SECURE_RELEASE_OUTCOMES - listed_non_secure)
    if missing_non_secure:
        blockers.append(
            _blocker(
                'RELEASE_POLICY_NON_SECURE_BOUNDARY_INCOMPLETE',
                missing_outcomes=missing_non_secure,
            )
        )

    return blockers


def _production_blocker_summary(tasks: Sequence[TaskboardTask]) -> dict[str, Any]:
    production_tasks = [task for task in tasks if task.is_production_task]
    blocked_tasks = [task for task in production_tasks if task.status == 'blocked']
    return {
        'production_task_count': len(production_tasks),
        'blocked_production_task_count': len(blocked_tasks),
        'blocked_production_tasks': [
            {
                'task_id': task.task_id,
                'title': task.title,
                'line': task.line,
                'blocked_reason': task.metadata.get('blocked_reason', ''),
            }
            for task in blocked_tasks
        ],
    }


def run_preflight(
    *,
    repo_root: Path | str | None = None,
    taskboard_path: Path | str = DEFAULT_TASKBOARD,
    retention_baseline_path: Path | str = DEFAULT_RETENTION_BASELINE,
    release_policy_path: Path | str = DEFAULT_RELEASE_POLICY,
    check_retention_baseline: bool = True,
    check_completed_outputs: bool = True,
) -> dict[str, Any]:
    """Run taskboard integrity checks and return a machine-readable report."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    taskboard = Path(taskboard_path)
    if not taskboard.is_absolute():
        taskboard = root / taskboard
    baseline = Path(retention_baseline_path)
    if not baseline.is_absolute():
        baseline = root / baseline
    policy = Path(release_policy_path)
    if not policy.is_absolute():
        policy = root / policy

    tasks, blockers = _read_taskboard(taskboard)
    if tasks:
        metadata_blockers = _task_metadata_blockers(tasks, root)
        if not check_completed_outputs:
            metadata_blockers = [
                blocker
                for blocker in metadata_blockers
                if blocker.get('code') != 'COMPLETED_TASK_OUTPUT_MISSING'
            ]
        blockers.extend(metadata_blockers)

    if check_retention_baseline:
        blockers.extend(_retention_presence_blockers(baseline, root))
    blockers.extend(_release_policy_blockers(policy, root))

    task_status_counts = {status: 0 for status in sorted(VALID_STATUSES)}
    task_status_counts['unrecognized'] = 0
    for task in tasks:
        if task.status in VALID_STATUSES:
            task_status_counts[task.status] += 1
        else:
            task_status_counts['unrecognized'] += 1

    production = _production_blocker_summary(tasks)
    blocked = bool(blockers)
    production_release_acceptable = not blocked and production['blocked_production_task_count'] == 0

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'checked_at_utc': _utc_now(),
        'repo_root': root.resolve().as_posix(),
        'taskboard_path': _relative(taskboard, root),
        'retention_baseline_path': _relative(baseline, root),
        'release_policy_path': _relative(policy, root),
        'overall_status': 'blocked' if blocked else 'pass',
        'supervisor_preflight_gate': 'blocked' if blocked else 'allowed',
        'ci_gate': 'fail' if blocked else 'pass',
        'proof_acceptance_blocked': blocked,
        'security_decision': SECURITY_DECISION_BLOCKED if blocked else SECURITY_DECISION_PASSED,
        'production_release_acceptable': production_release_acceptable,
        'production_release_decision': (
            'eligible-for-acceptance'
            if production_release_acceptable
            else 'blocked-production'
        ),
        'summary': {
            'task_count': len(tasks),
            'task_status_counts': task_status_counts,
            'blocker_count': len(blockers),
            **production,
        },
        'tasks': [
            {
                'task_id': task.task_id,
                'title': task.title,
                'line': task.line,
                'status': task.status,
                'priority': task.metadata.get('priority', ''),
                'track': task.metadata.get('track', ''),
                'depends_on': task.depends_on,
                'outputs': task.outputs,
                'is_production_task': task.is_production_task,
            }
            for task in tasks
        ],
        'blockers': blockers,
        'restoration_runbook': {
            'supervisor_recovery': 'scripts/ops/security_verification/restore_crypto_exchange_security_tree.py',
            'retention_policy': 'docs/security_verification/taskboard_artifact_retention_policy.md',
            'preflight_ci': 'docs/security_verification/taskboard_preflight_ci.md',
        },
    }


def write_json(document: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def build_github_summary_lines(report: Mapping[str, Any]) -> list[str]:
    summary = report.get('summary') if isinstance(report.get('summary'), Mapping) else {}
    lines = [
        '## Crypto Exchange Taskboard Preflight',
        '',
        f"- status: `{report.get('overall_status', '<missing>')}`",
        f"- CI gate: `{report.get('ci_gate', '<missing>')}`",
        f"- supervisor gate: `{report.get('supervisor_preflight_gate', '<missing>')}`",
        f"- production release decision: `{report.get('production_release_decision', '<missing>')}`",
        f"- production release acceptable: `{report.get('production_release_acceptable', '<missing>')}`",
        f"- tasks parsed: `{summary.get('task_count', 0)}`",
        f"- blockers: `{summary.get('blocker_count', 0)}`",
    ]
    blockers = report.get('blockers')
    if isinstance(blockers, list) and blockers:
        lines.extend(['', '### Blockers'])
        for blocker in blockers[:20]:
            if isinstance(blocker, Mapping):
                code = blocker.get('code', '<missing>')
                task_id = blocker.get('task_id')
                path = blocker.get('path')
                target = f" `{task_id}`" if task_id else f" `{path}`" if path else ''
                lines.append(f"- `{code}`{target}")
    return lines


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Preflight crypto_exchange taskboard integrity before CI or supervisor work.'
    )
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root to inspect')
    parser.add_argument('--taskboard', default=DEFAULT_TASKBOARD.as_posix(), help='taskboard markdown path')
    parser.add_argument(
        '--retention-baseline',
        default=DEFAULT_RETENTION_BASELINE.as_posix(),
        help='artifact retention baseline used for presence checks',
    )
    parser.add_argument(
        '--release-policy',
        default=DEFAULT_RELEASE_POLICY.as_posix(),
        help='security decision policy artifact to verify',
    )
    parser.add_argument('--out', help='optional JSON report path')
    parser.add_argument(
        '--skip-retention-baseline',
        action='store_true',
        help='skip PORTAL-CXTP-057 retained-artifact presence checks',
    )
    parser.add_argument(
        '--skip-completed-output-check',
        action='store_true',
        help='skip completed-task output presence checks',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)
    report = run_preflight(
        repo_root=repo_root,
        taskboard_path=Path(args.taskboard),
        retention_baseline_path=Path(args.retention_baseline),
        release_policy_path=Path(args.release_policy),
        check_retention_baseline=not args.skip_retention_baseline,
        check_completed_outputs=not args.skip_completed_output_check,
    )

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = repo_root / out_path
        write_json(report, out_path)
        print(json.dumps({'report': _relative(out_path, repo_root), 'status': report['overall_status']}))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    return 2 if report['overall_status'] == 'blocked' else 0


if __name__ == '__main__':
    sys.exit(main())
