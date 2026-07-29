"""Assumption ownership and freshness checks for crypto-exchange proofs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .ir.schema import SecurityModelIR, as_security_model_ir, evidence_review_statuses, validate_ir


def _parse_as_of(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('as_of must be an ISO timestamp or datetime')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _assumption_id(assumption: Mapping[str, Any] | str) -> str:
    if isinstance(assumption, str):
        return assumption
    return str(assumption.get('id', '')).strip()


def _assumption_mapping(assumption: Mapping[str, Any] | str) -> Mapping[str, Any]:
    return assumption if isinstance(assumption, Mapping) else {'id': assumption}


def _required_ids(model: SecurityModelIR, required_assumptions: Iterable[str] | None) -> list[str]:
    if required_assumptions is not None:
        values = {str(item).strip() for item in required_assumptions if str(item).strip()}
    else:
        values = {_assumption_id(item) for item in model.assumptions}
    return sorted(values, key=lambda item: (item[:1], int(item[1:]) if item[1:].isdigit() else item[1:]))


def _expiry_status(assumption: Mapping[str, Any], as_of: datetime) -> tuple[bool, bool, str | None]:
    expires_at = assumption.get('evidence_expires_at')
    if not isinstance(expires_at, str) or not expires_at.strip():
        return False, False, None
    parsed = _parse_as_of(expires_at)
    return parsed >= as_of, parsed < as_of, _format_timestamp(parsed)


def evaluate_assumption_registry(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    required_assumptions: Iterable[str] | None = None,
    accepted_assumptions: Iterable[str] | None = None,
    as_of: str | datetime | None = None,
    require_owner: bool = True,
    require_evidence: bool = True,
    require_current: bool = True,
) -> dict[str, Any]:
    """Evaluate assumption ownership, evidence, and freshness."""

    normalized = validate_ir(as_security_model_ir(model))
    as_of_dt = _parse_as_of(as_of)
    accepted = None if accepted_assumptions is None else {str(item).strip() for item in accepted_assumptions if str(item).strip()}
    assumptions_by_id = {
        _assumption_id(assumption): _assumption_mapping(assumption)
        for assumption in normalized.assumptions
        if _assumption_id(assumption)
    }
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []

    for assumption_id in _required_ids(normalized, required_assumptions):
        assumption = assumptions_by_id.get(assumption_id)
        if assumption is None:
            record = {
                'assumption_id': assumption_id,
                'present': False,
                'owned': False,
                'evidenced': False,
                'current': False,
                'accepted': accepted is None or assumption_id in accepted,
                'reasons': ['missing assumption entry'],
            }
            records.append(record)
            failures.append(record)
            continue

        owner = assumption.get('owner')
        evidence_refs = assumption.get('evidence_refs', [])
        if not isinstance(evidence_refs, list):
            evidence_refs = []
        current, stale, expires_at = _expiry_status(assumption, as_of_dt)
        review_statuses = sorted(evidence_review_statuses(evidence_refs))
        record = {
            'assumption_id': assumption_id,
            'present': True,
            'description': assumption.get('description', ''),
            'owner': owner if isinstance(owner, str) else '',
            'owned': isinstance(owner, str) and bool(owner.strip()),
            'evidenced': bool(evidence_refs),
            'review_statuses': review_statuses,
            'last_reviewed_at': assumption.get('last_reviewed_at', ''),
            'evidence_expires_at': expires_at or '',
            'current': current,
            'stale': stale,
            'accepted': accepted is None or assumption_id in accepted,
            'reasons': [],
        }
        if require_owner and not record['owned']:
            record['reasons'].append('missing operational owner')
        if require_evidence and not record['evidenced']:
            record['reasons'].append('missing evidence references')
        if require_current and not expires_at:
            record['reasons'].append('missing evidence_expires_at')
        elif require_current and not current:
            record['reasons'].append('evidence is stale')
        if accepted is not None and assumption_id not in accepted:
            record['reasons'].append('assumption was not accepted')

        records.append(record)
        if record['reasons']:
            failures.append(record)
        elif record['stale']:
            attention.append(record)

    summary = {
        'total': len(records),
        'present': sum(bool(record['present']) for record in records),
        'owned': sum(bool(record['owned']) for record in records),
        'evidenced': sum(bool(record['evidenced']) for record in records),
        'current': sum(bool(record['current']) for record in records),
        'stale': sum(bool(record.get('stale')) for record in records),
        'accepted': sum(bool(record['accepted']) for record in records),
    }
    return {
        'as_of': _format_timestamp(as_of_dt),
        'release_ready': not failures,
        'require_owner': require_owner,
        'require_evidence': require_evidence,
        'require_current': require_current,
        'summary': summary,
        'assumptions': records,
        'failures': failures,
        'attention': attention,
    }
