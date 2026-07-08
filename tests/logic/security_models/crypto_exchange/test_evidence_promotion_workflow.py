import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.evidence_promotion import (
    EVIDENCE_PROMOTION_SCHEMA_VERSION,
    evaluate_evidence_promotion_workflow,
)


ROOT = Path(__file__).resolve().parents[4]
DOC_PATH = ROOT / 'docs' / 'security_verification' / 'evidence_promotion_workflow.md'
TEMPLATE_PATH = ROOT / 'security_ir_artifacts' / 'assurance-run' / 'evidence-review-template.json'


def _digest(char: str = 'a') -> str:
    return char * 64


def _promotion_record(**overrides):
    record = {
        'fact_id': 'policy.authorization_required',
        'claim_id': 'no_unauthorized_withdrawal',
        'release_gate': 'blocking',
        'source_review_status': 'machine_extracted',
        'decision': 'promote',
        'promoted_review_status': 'human_reviewed',
        'reviewer': {
            'id': 'reviewer@example.com',
            'reviewed_at': '2026-07-08T00:00:00Z',
        },
        'source_digest': {
            'algorithm': 'sha256',
            'value': _digest('b'),
        },
        'expires_at': '2027-01-08T00:00:00Z',
        'evidence_ref': {
            'kind': 'source_code',
            'path': 'wallet/withdrawals.py',
            'review_status': 'machine_extracted',
            'line_start': 12,
            'line_end': 48,
        },
    }
    record.update(overrides)
    return record


def _payload(records):
    return {
        'schema_version': EVIDENCE_PROMOTION_SCHEMA_VERSION,
        'evidence_reviews': list(records),
    }


def test_expected_workflow_artifacts_exist_and_define_contract() -> None:
    assert DOC_PATH.is_file()
    assert TEMPLATE_PATH.is_file()

    markdown = DOC_PATH.read_text(encoding='utf-8')
    assert 'heuristic' in markdown
    assert 'machine_extracted' in markdown
    assert 'human_reviewed' in markdown
    assert 'trusted_fixture' in markdown
    assert 'source digest' in markdown.lower()
    assert 'quarantine' in markdown.lower()

    template = json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))
    assert template['schema_version'] == EVIDENCE_PROMOTION_SCHEMA_VERSION
    assert template['review_policy']['unreviewed_critical_fact_behavior'] == 'quarantine_release_blocking'


def test_template_is_machine_checkable_and_quarantines_unreviewed_blocking_fact() -> None:
    template = json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))

    evaluation = evaluate_evidence_promotion_workflow(template, as_of='2026-07-09T00:00:00Z')

    assert evaluation['summary'] == {
        'total_reviews': 2,
        'promoted': 1,
        'quarantined': 1,
        'failures': 0,
    }
    assert evaluation['release_ready'] is False
    promoted_ref = evaluation['promoted_evidence_refs'][0]['evidence_ref']
    assert promoted_ref['review_status'] == 'human_reviewed'
    assert promoted_ref['reviewer_id'] == 'security-reviewer@example.com'
    assert promoted_ref['sha256'] == _digest('a')
    assert promoted_ref['line_start'] == 1
    assert promoted_ref['line_end'] == 80
    assert evaluation['quarantined_facts'][0]['blocking_behavior'] == 'release_blocking'


def test_valid_promotion_adds_reviewer_digest_span_and_expiry_to_ref() -> None:
    evaluation = evaluate_evidence_promotion_workflow(
        _payload([_promotion_record()]),
        as_of='2026-07-09T00:00:00Z',
    )

    assert evaluation['release_ready'] is True
    assert evaluation['failures'] == []
    assert evaluation['quarantined_facts'] == []

    promoted = evaluation['promoted_evidence_refs'][0]
    assert promoted['fact_id'] == 'policy.authorization_required'
    evidence_ref = promoted['evidence_ref']
    assert evidence_ref['review_status'] == 'human_reviewed'
    assert evidence_ref['reviewer_id'] == 'reviewer@example.com'
    assert evidence_ref['reviewed_at'] == '2026-07-08T00:00:00Z'
    assert evidence_ref['evidence_expires_at'] == '2027-01-08T00:00:00Z'
    assert evidence_ref['sha256'] == _digest('b')
    assert evidence_ref['line_start'] == 12
    assert evidence_ref['line_end'] == 48


def test_trusted_fixture_promotion_can_use_trace_identifier_instead_of_line_span() -> None:
    record = _promotion_record(
        promoted_review_status='trusted_fixture',
        evidence_ref={
            'kind': 'audit_log',
            'path': 'security_ir_artifacts/assurance-run/runtime-trace.json',
            'review_status': 'heuristic',
            'trace_identifier': 'trace:withdrawal:42',
        },
    )

    evaluation = evaluate_evidence_promotion_workflow(
        _payload([record]),
        as_of='2026-07-09T00:00:00Z',
    )

    evidence_ref = evaluation['promoted_evidence_refs'][0]['evidence_ref']
    assert evaluation['release_ready'] is True
    assert evidence_ref['review_status'] == 'trusted_fixture'
    assert evidence_ref['trace_identifier'] == 'trace:withdrawal:42'


def test_missing_digest_or_locator_fails_and_quarantines_blocking_fact() -> None:
    record = _promotion_record(
        source_digest={'algorithm': 'sha256', 'value': 'not-a-digest'},
        evidence_ref={
            'kind': 'source_code',
            'path': 'wallet/withdrawals.py',
            'review_status': 'machine_extracted',
        },
    )

    evaluation = evaluate_evidence_promotion_workflow(
        _payload([record]),
        as_of='2026-07-09T00:00:00Z',
    )

    assert evaluation['release_ready'] is False
    assert evaluation['summary']['promoted'] == 0
    assert evaluation['summary']['quarantined'] == 1
    assert 'sha256' in evaluation['failures'][0]['reason']


def test_stale_promotion_fails_closed_for_blocking_fact() -> None:
    evaluation = evaluate_evidence_promotion_workflow(
        _payload([_promotion_record(expires_at='2026-07-08T12:00:00Z')]),
        as_of='2026-07-09T00:00:00Z',
    )

    assert evaluation['release_ready'] is False
    assert evaluation['summary']['quarantined'] == 1
    assert evaluation['failures'][0]['reason'] == 'expires_at must not be stale at evaluation time'


def test_invalid_source_status_cannot_emit_promoted_reference() -> None:
    evaluation = evaluate_evidence_promotion_workflow(
        _payload([_promotion_record(source_review_status='human_reviewed')]),
        as_of='2026-07-09T00:00:00Z',
    )

    assert evaluation['release_ready'] is False
    assert evaluation['promoted_evidence_refs'] == []
    assert evaluation['summary']['quarantined'] == 1
    assert evaluation['failures'][0]['reason'].startswith('source_review_status must be one of')


def test_missing_evidence_ref_quarantines_blocking_promotion_attempt() -> None:
    record = _promotion_record()
    record.pop('evidence_ref')

    evaluation = evaluate_evidence_promotion_workflow(
        _payload([record]),
        as_of='2026-07-09T00:00:00Z',
    )

    assert evaluation['release_ready'] is False
    assert evaluation['promoted_evidence_refs'] == []
    assert evaluation['summary']['quarantined'] == 1
    assert evaluation['failures'][0]['reason'] == 'evidence_ref must be a mapping for promotion'


def test_unreviewed_blocking_fact_must_be_explicitly_quarantined() -> None:
    record = _promotion_record(decision='reject')

    evaluation = evaluate_evidence_promotion_workflow(
        _payload([record]),
        as_of='2026-07-09T00:00:00Z',
    )

    assert evaluation['release_ready'] is False
    assert evaluation['summary']['quarantined'] == 1
    assert evaluation['failures'][0]['reason'] == (
        'unreviewed blocking/high fact must be quarantined until reviewed evidence is supplied'
    )
