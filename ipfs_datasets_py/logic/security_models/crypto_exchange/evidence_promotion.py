"""Reviewed-evidence promotion workflow for crypto-exchange proof facts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable, Mapping

from .ir.schema import EVIDENCE_KINDS, EVIDENCE_REVIEW_STATUSES


EVIDENCE_PROMOTION_SCHEMA_VERSION = 'crypto-exchange-evidence-promotion/v1'
SOURCE_REVIEW_STATUSES = frozenset({'heuristic', 'machine_extracted'})
PROMOTED_REVIEW_STATUSES = frozenset({'human_reviewed', 'trusted_fixture'})
REVIEWED_EVIDENCE_DECISIONS = frozenset({'promote', 'quarantine', 'reject'})
CRITICAL_RELEASE_GATES = frozenset({'blocking', 'high'})
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


def _parse_timestamp(field_name: str, value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field_name} must be a non-empty ISO timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{field_name} must be an ISO timestamp') from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _as_of(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return _parse_timestamp('as_of', value)


def _string_field(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field_name} must be a non-empty string')
    return value.strip()


def _optional_mapping(record: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    value = record.get(field_name, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f'{field_name} must be a mapping when present')
    return value


def _digest_value(review: Mapping[str, Any], evidence_ref: Mapping[str, Any]) -> str:
    source_digest = review.get('source_digest')
    if isinstance(source_digest, str):
        digest = source_digest.strip().lower()
    elif isinstance(source_digest, Mapping):
        algorithm = str(source_digest.get('algorithm', '')).strip().lower()
        if algorithm != 'sha256':
            raise ValueError('source_digest.algorithm must be sha256')
        digest = str(source_digest.get('value', '')).strip().lower()
    else:
        digest = str(evidence_ref.get('sha256', '')).strip().lower()
    if not SHA256_RE.fullmatch(digest):
        raise ValueError('source digest must be a lowercase 64-character sha256 hex string')
    return digest


def _positive_int(field_name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f'{field_name} must be a positive integer')
    return value


def _line_span(review: Mapping[str, Any], evidence_ref: Mapping[str, Any]) -> dict[str, int] | None:
    location = review.get('source_location')
    if location is None:
        location = {}
    if not isinstance(location, Mapping):
        raise ValueError('source_location must be a mapping when present')
    line_start = evidence_ref.get('line_start', location.get('line_start'))
    line_end = evidence_ref.get('line_end', location.get('line_end'))
    if line_start is None and line_end is None:
        return None
    start = _positive_int('line_start', line_start)
    end = _positive_int('line_end', line_end)
    if end < start:
        raise ValueError('line_end must be >= line_start')
    return {'line_start': start, 'line_end': end}


def _trace_identifier(review: Mapping[str, Any], evidence_ref: Mapping[str, Any]) -> str | None:
    for field_name in ('trace_identifier', 'trace_id'):
        value = review.get(field_name, evidence_ref.get(field_name))
        if isinstance(value, str) and value.strip():
            return value.strip()
    trace = review.get('trace')
    if isinstance(trace, Mapping):
        value = trace.get('trace_id') or trace.get('event_id')
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _validate_evidence_ref(evidence_ref: Mapping[str, Any], promoted_status: str) -> None:
    kind = evidence_ref.get('kind')
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f'Unsupported evidence ref kind: {kind}')
    path = evidence_ref.get('path')
    if not isinstance(path, str) or not path.strip():
        raise ValueError('evidence_ref.path must be a non-empty string')
    status = evidence_ref.get('review_status', promoted_status)
    if status not in EVIDENCE_REVIEW_STATUSES:
        raise ValueError(f'Unsupported evidence review status: {status}')
    if status not in SOURCE_REVIEW_STATUSES | PROMOTED_REVIEW_STATUSES:
        raise ValueError(f'Unsupported promotion evidence review status: {status}')


def _failure(
    review: Mapping[str, Any],
    reason: str,
    *,
    release_gate: str = '',
    decision: str = '',
) -> dict[str, Any]:
    return {
        'fact_id': str(review.get('fact_id', '')).strip(),
        'claim_id': str(review.get('claim_id', '')).strip(),
        'release_gate': release_gate or str(review.get('release_gate', '')).strip(),
        'decision': decision or str(review.get('decision', '')).strip(),
        'reason': reason,
    }


def _quarantine_record(
    review: Mapping[str, Any],
    *,
    reason: str,
    release_gate: str,
    decision: str,
) -> dict[str, Any]:
    quarantine = _optional_mapping(review, 'quarantine')
    return {
        'fact_id': str(review.get('fact_id', '')).strip(),
        'claim_id': str(review.get('claim_id', '')).strip(),
        'release_gate': release_gate,
        'decision': decision,
        'source_review_status': str(review.get('source_review_status', '')).strip(),
        'reason': str(quarantine.get('reason') or reason).strip(),
        'blocking_behavior': str(quarantine.get('blocking_behavior') or 'release_blocking').strip(),
        'until': str(quarantine.get('until') or 'reviewed_evidence_supplied').strip(),
    }


def _promoted_ref(
    review: Mapping[str, Any],
    evidence_ref: Mapping[str, Any],
    *,
    promoted_status: str,
    reviewer_id: str,
    reviewed_at: str,
    expires_at: str,
    digest: str,
    line_span: dict[str, int] | None,
    trace_identifier: str | None,
) -> dict[str, Any]:
    promoted = dict(evidence_ref)
    promoted['review_status'] = promoted_status
    promoted['sha256'] = digest
    promoted['reviewer_id'] = reviewer_id
    promoted['reviewed_at'] = reviewed_at
    promoted['evidence_expires_at'] = expires_at
    if line_span:
        promoted['line_start'] = line_span['line_start']
        promoted['line_end'] = line_span['line_end']
    if trace_identifier:
        promoted['trace_identifier'] = trace_identifier
    return {
        'fact_id': _string_field(review, 'fact_id'),
        'claim_id': _string_field(review, 'claim_id'),
        'release_gate': _string_field(review, 'release_gate'),
        'evidence_ref': promoted,
    }


def _evaluate_one_review(
    review: Mapping[str, Any],
    *,
    as_of: datetime,
    critical_release_gates: frozenset[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    try:
        _string_field(review, 'fact_id')
        _string_field(review, 'claim_id')
        release_gate = _string_field(review, 'release_gate')
        source_status = _string_field(review, 'source_review_status')
        decision = _string_field(review, 'decision')
    except ValueError as exc:
        return None, None, [_failure(review, str(exc))]

    if source_status not in SOURCE_REVIEW_STATUSES:
        failures.append(
            _failure(
                review,
                f'source_review_status must be one of {sorted(SOURCE_REVIEW_STATUSES)}',
                release_gate=release_gate,
                decision=decision,
            )
        )
    if decision not in REVIEWED_EVIDENCE_DECISIONS:
        failures.append(
            _failure(
                review,
                f'decision must be one of {sorted(REVIEWED_EVIDENCE_DECISIONS)}',
                release_gate=release_gate,
                decision=decision,
            )
        )

    critical = release_gate in critical_release_gates
    if failures:
        quarantine = None
        if critical:
            quarantine = _quarantine_record(
                review,
                reason='promotion failed validation for a proof-critical fact',
                release_gate=release_gate,
                decision='quarantine',
            )
        return None, quarantine, failures

    if decision != 'promote':
        quarantine = _quarantine_record(
            review,
            reason='unreviewed proof-critical evidence is not release eligible',
            release_gate=release_gate,
            decision=decision,
        )
        if critical and decision != 'quarantine':
            failures.append(_failure(review, 'unreviewed blocking/high fact must be quarantined until reviewed evidence is supplied', release_gate=release_gate, decision=decision))
        if critical:
            return None, quarantine, failures
        return None, None, failures

    evidence_ref = review.get('evidence_ref')
    if not isinstance(evidence_ref, Mapping):
        failures.append(
            _failure(
                review,
                'evidence_ref must be a mapping for promotion',
                release_gate=release_gate,
                decision=decision,
            )
        )
        quarantine = None
        if critical:
            quarantine = _quarantine_record(
                review,
                reason='promotion failed validation for a proof-critical fact',
                release_gate=release_gate,
                decision='quarantine',
            )
        return None, quarantine, failures

    try:
        promoted_status = _string_field(review, 'promoted_review_status')
        if promoted_status not in PROMOTED_REVIEW_STATUSES:
            raise ValueError(
                f'promoted_review_status must be one of {sorted(PROMOTED_REVIEW_STATUSES)}'
            )
        _validate_evidence_ref(evidence_ref, promoted_status)
        reviewer = _optional_mapping(review, 'reviewer')
        reviewer_id = _string_field(reviewer, 'id')
        reviewed_at_dt = _parse_timestamp('reviewer.reviewed_at', reviewer.get('reviewed_at'))
        expires_at_dt = _parse_timestamp('expires_at', review.get('expires_at'))
        if expires_at_dt < reviewed_at_dt:
            raise ValueError('expires_at must be >= reviewer.reviewed_at')
        if expires_at_dt < as_of:
            raise ValueError('expires_at must not be stale at evaluation time')
        digest = _digest_value(review, evidence_ref)
        line_span = _line_span(review, evidence_ref)
        trace_identifier = _trace_identifier(review, evidence_ref)
        if line_span is None and trace_identifier is None:
            raise ValueError('promotion requires either a source line span or trace identifier')
        promoted = _promoted_ref(
            review,
            evidence_ref,
            promoted_status=promoted_status,
            reviewer_id=reviewer_id,
            reviewed_at=_format_timestamp(reviewed_at_dt),
            expires_at=_format_timestamp(expires_at_dt),
            digest=digest,
            line_span=line_span,
            trace_identifier=trace_identifier,
        )
    except ValueError as exc:
        failures.append(_failure(review, str(exc), release_gate=release_gate, decision=decision))
        if critical:
            return None, _quarantine_record(
                review,
                reason='promotion failed validation for a proof-critical fact',
                release_gate=release_gate,
                decision='quarantine',
            ), failures
        return None, None, failures

    return promoted, None, failures


def evaluate_evidence_promotion_workflow(
    payload: Mapping[str, Any],
    *,
    as_of: str | datetime | None = None,
    critical_release_gates: Iterable[str] = CRITICAL_RELEASE_GATES,
) -> dict[str, Any]:
    """Validate reviewed-evidence promotions and quarantine unreviewed critical facts.

    The workflow promotes only ``heuristic`` or ``machine_extracted`` evidence to
    ``human_reviewed`` or ``trusted_fixture`` when reviewer identity, source
    digest, source location or trace identity, and expiry are present. Critical
    blocking/high facts that are not validly promoted are returned as quarantined
    release blockers.
    """

    if not isinstance(payload, Mapping):
        raise ValueError('evidence promotion payload must be a mapping')
    schema_version = payload.get('schema_version')
    if schema_version != EVIDENCE_PROMOTION_SCHEMA_VERSION:
        raise ValueError(f'schema_version must be {EVIDENCE_PROMOTION_SCHEMA_VERSION}')
    reviews = payload.get('evidence_reviews')
    if not isinstance(reviews, list):
        raise ValueError('evidence_reviews must be a list')

    critical_gates = frozenset(str(item) for item in critical_release_gates)
    as_of_dt = _as_of(as_of)
    promoted_refs: list[dict[str, Any]] = []
    quarantined_facts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, review in enumerate(reviews):
        if not isinstance(review, Mapping):
            failures.append(
                {
                    'fact_id': '',
                    'claim_id': '',
                    'release_gate': '',
                    'decision': '',
                    'reason': f'evidence_reviews[{index}] must be a mapping',
                }
            )
            continue
        promoted, quarantine, review_failures = _evaluate_one_review(
            review,
            as_of=as_of_dt,
            critical_release_gates=critical_gates,
        )
        if promoted is not None:
            promoted_refs.append(promoted)
        if quarantine is not None:
            quarantined_facts.append(quarantine)
        failures.extend(review_failures)

    summary = {
        'total_reviews': len(reviews),
        'promoted': len(promoted_refs),
        'quarantined': len(quarantined_facts),
        'failures': len(failures),
    }
    return {
        'schema_version': EVIDENCE_PROMOTION_SCHEMA_VERSION,
        'as_of': _format_timestamp(as_of_dt),
        'release_ready': not failures and not quarantined_facts,
        'source_review_statuses': sorted(SOURCE_REVIEW_STATUSES),
        'promoted_review_statuses': sorted(PROMOTED_REVIEW_STATUSES),
        'critical_release_gates': sorted(critical_gates),
        'summary': summary,
        'promoted_evidence_refs': promoted_refs,
        'quarantined_facts': quarantined_facts,
        'failures': failures,
    }
