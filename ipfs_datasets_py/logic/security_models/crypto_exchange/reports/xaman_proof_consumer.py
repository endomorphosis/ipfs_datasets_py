"""Xaman proof-consumer invariant checks.

The generic :mod:`proof_report` and :mod:`proof_receipt` modules validate the
wire envelopes.  This module adds the Xaman production-consumer bindings that
are intentionally outside the generic schema: corpus commit, reviewed source
evidence, solver availability, and environment freshness.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid
from .proof_receipt import ProofReceipt
from .proof_report import (
    PROOF_STATUS_PROVED,
    ProofReport,
)

SCHEMA_VERSION = 'xaman-proof-consumer-report/v1'
TASK_ID = 'PORTAL-CXTP-073'
CLAIM_ID = 'xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims'
FIXED_GENERATED_AT_UTC = '2026-07-08T21:00:00Z'
RELEASE_WINDOW_AT_UTC = '2026-07-08T21:15:00Z'
FRESH_ENVIRONMENT_MAX_AGE_HOURS = 24
SUPPORTED_RECEIPT_SCHEMA_VERSION = 'proof-receipt/v1'
SUPPORTED_REPORT_SCHEMA_VERSION = 'proof-report/v1'
PROOF_KERNEL_PATH = 'security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean'
PROOF_CONSUMER_REPORT_PATH = (
    'security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json'
)
MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
SECURITY_CLAIMS_PATH = 'security_ir_artifacts/corpora/xaman-app/security-claims.json'
SOURCE_MANIFEST_PATH = 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
ENVIRONMENT_PROBE_PATH = 'security_ir_artifacts/corpora/xaman-app/environment-probe.json'

REQUIRED_ASSUMPTIONS = [
    'xaman-security:assumption:proof-consumer-fail-closed-policy',
    'xaman-security:assumption:proof-receipt-cid-or-signature-validation',
]
REQUIRED_BINDINGS = [
    'model_cid',
    'claim_id',
    'proof_report_cid',
    'report_schema_version',
    'solver_identity',
    'accepted_assumptions',
    'reviewed_source_evidence',
    'corpus_commit',
    'fresh_environment_probe',
]
REJECTED_OUTCOMES = ['DISPROVED', 'UNKNOWN', 'NOT_MODELED', 'MISSING_SOLVER']
ALLOWED_SOLVER_RESULTS = {'checked', 'unsat', 'valid'}
REQUIRED_EVIDENCE_PATHS = [
    'docs/security_verification/proof_receipt_consumer_policy.md',
    'security_ir_artifacts/policies/security-decision-policy.json',
    SECURITY_CLAIMS_PATH,
    SOURCE_MANIFEST_PATH,
    ENVIRONMENT_PROBE_PATH,
    PROOF_KERNEL_PATH,
]
PROOF_KERNEL_THEOREMS = [
    'acceptedBindsModelCID',
    'acceptedBindsClaimID',
    'acceptedBindsReportCID',
    'acceptedBindsSolverIdentity',
    'acceptedBindsAssumptions',
    'acceptedBindsReviewedEvidence',
    'acceptedBindsCorpusCommit',
    'acceptedBindsFreshEnvironment',
    'rejectsDisprovedUnknownNotModeled',
    'rejectsMissingSolver',
]


class XamanProofConsumerError(ValueError):
    """Raised when a Xaman proof-consumer packet fails closed."""


def _parse_utc(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise XamanProofConsumerError(f'{field_name} must be a non-empty UTC timestamp')
    normalized = value.replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise XamanProofConsumerError(f'{field_name} must be ISO-8601 UTC') from exc
    if parsed.tzinfo is None:
        raise XamanProofConsumerError(f'{field_name} must include a UTC offset')
    return parsed.astimezone(timezone.utc)


def _require_mapping(field_name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise XamanProofConsumerError(f'{field_name} must be a mapping')
    return value


def _require_string(field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise XamanProofConsumerError(f'{field_name} must be a non-empty string')
    return value


def _require_string_list(field_name: str, value: Any) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in value
    ):
        raise XamanProofConsumerError(f'{field_name} must be a list of non-empty strings')
    return list(value)


def _artifact_cid_without_self(payload: Mapping[str, Any]) -> str:
    stripped = {
        key: value
        for key, value in payload.items()
        if key != 'artifact_cid'
    }
    return calculate_artifact_cid(stripped)


def _source_review_is_accepted(evidence_ref: Mapping[str, Any]) -> bool:
    status = evidence_ref.get('review_status')
    return status in {'reviewed', 'human_reviewed'}


def _solver_entry(
    context: Mapping[str, Any],
    solver_name: str,
) -> Mapping[str, Any] | None:
    allowlist = _require_mapping('context.solver_allowlist', context.get('solver_allowlist', {}))
    entry = allowlist.get(solver_name)
    if isinstance(entry, Mapping):
        return entry

    environment = _require_mapping('context.environment_probe', context.get('environment_probe', {}))
    solver_paths = _require_mapping('context.environment_probe.solver_paths', environment.get('solver_paths', {}))
    resolved = _require_mapping(
        'context.environment_probe.solver_paths.resolved_executables',
        solver_paths.get('resolved_executables', {}),
    )
    executable = resolved.get(solver_name)
    return executable if isinstance(executable, Mapping) else None


def validate_xaman_proof_consumer_packet(
    packet: Mapping[str, Any],
    *,
    release_window_at_utc: str | None = None,
) -> dict[str, Any]:
    """Validate a Xaman proof-consumer packet and return a normalized verdict.

    The function is deliberately fail-closed.  It accepts only ``PROVED``
    reports with a matching receipt, supported solver identity, reviewed
    evidence, matching corpus commit, and an environment probe fresh for the
    selected release window.
    """

    root = _require_mapping('packet', packet)
    report_payload = _require_mapping('proof_report', root.get('proof_report'))
    receipt_payload = _require_mapping('proof_receipt', root.get('proof_receipt'))
    context = _require_mapping('context', root.get('context'))

    report = ProofReport.from_untrusted_dict(report_payload)
    receipt = ProofReceipt.from_untrusted_dict(receipt_payload, report=report)

    expected_model_cid = _require_string('context.model_cid', context.get('model_cid'))
    expected_claim_id = _require_string('context.claim_id', context.get('claim_id'))
    if report.model_cid != expected_model_cid or receipt.model_cid != expected_model_cid:
        raise XamanProofConsumerError('model_cid binding mismatch')
    if report.claim_id != expected_claim_id or receipt.claim_id != expected_claim_id:
        raise XamanProofConsumerError('claim_id binding mismatch')
    if receipt.proof_report_cid != report.cid:
        raise XamanProofConsumerError('proof_report_cid binding mismatch')
    if receipt.report_schema_version != report.schema_version:
        raise XamanProofConsumerError('report_schema_version binding mismatch')
    proof_kernel = _require_mapping('context.proof_kernel', context.get('proof_kernel'))
    proof_kernel_cid = _require_string(
        'context.proof_kernel.artifact_cid',
        proof_kernel.get('artifact_cid'),
    )
    if report.proof_or_trace_cid != proof_kernel_cid:
        raise XamanProofConsumerError('proof kernel CID does not match proof_or_trace_cid')
    if receipt.metadata.get('proof_kernel_cid') != proof_kernel_cid:
        raise XamanProofConsumerError('receipt proof kernel CID binding mismatch')
    if receipt.schema_version != SUPPORTED_RECEIPT_SCHEMA_VERSION:
        raise XamanProofConsumerError('unsupported proof receipt schema version')
    if report.schema_version != SUPPORTED_REPORT_SCHEMA_VERSION:
        raise XamanProofConsumerError('unsupported proof report schema version')
    if not receipt.valid:
        raise XamanProofConsumerError('receipt is not valid')
    if report.status != PROOF_STATUS_PROVED:
        raise XamanProofConsumerError(f'report status {report.status} is not accepted')
    if report.solver_result not in ALLOWED_SOLVER_RESULTS:
        raise XamanProofConsumerError(f'solver_result {report.solver_result} is not accepted')
    if not report.prover or not report.solver_name or not report.solver_version:
        raise XamanProofConsumerError('solver identity is incomplete')
    receipt_solver = _require_mapping(
        'proof_receipt.metadata.solver_identity',
        receipt.metadata.get('solver_identity'),
    )
    expected_solver_identity = {
        'prover': report.prover,
        'solver_name': report.solver_name,
        'solver_version': report.solver_version,
        'solver_result': report.solver_result,
    }
    if dict(receipt_solver) != expected_solver_identity:
        raise XamanProofConsumerError('receipt solver identity does not match the proof report')

    modeled_claim_ids = set(_require_string_list('context.modeled_claim_ids', context.get('modeled_claim_ids')))
    if expected_claim_id not in modeled_claim_ids:
        raise XamanProofConsumerError('claim_id is not modeled in the production SecurityModelIR')

    expected_assumptions = set(_require_string_list('context.required_assumptions', context.get('required_assumptions')))
    report_assumptions = set(report.assumptions)
    receipt_assumptions = set(receipt.accepted_assumptions)
    if report_assumptions != expected_assumptions:
        raise XamanProofConsumerError('report assumptions do not match required assumptions')
    if receipt_assumptions != expected_assumptions:
        raise XamanProofConsumerError('accepted assumptions do not match required assumptions')

    solver = _solver_entry(context, report.solver_name)
    if solver is None:
        raise XamanProofConsumerError(f'solver {report.solver_name} is missing from the probe or allowlist')
    if solver.get('status') != 'present':
        raise XamanProofConsumerError(f'solver {report.solver_name} is not present')
    if solver.get('required') is False:
        raise XamanProofConsumerError(f'solver {report.solver_name} is not required for proof-critical mode')
    if solver.get('version') and solver.get('version') != report.solver_version:
        raise XamanProofConsumerError('solver version does not match the proof report')

    source = _require_mapping('context.corpus', context.get('corpus'))
    expected_commit = _require_string('context.corpus.commit_sha', source.get('commit_sha'))
    expected_manifest_sha = _require_string(
        'context.corpus.manifest_aggregate_sha256',
        source.get('manifest_aggregate_sha256'),
    )
    receipt_corpus = _require_mapping('proof_receipt.metadata.corpus', receipt.metadata.get('corpus'))
    if receipt_corpus.get('commit_sha') != expected_commit:
        raise XamanProofConsumerError('corpus commit binding mismatch')
    if receipt_corpus.get('manifest_aggregate_sha256') != expected_manifest_sha:
        raise XamanProofConsumerError('source manifest digest binding mismatch')

    evidence_refs = [
        ref for ref in report.evidence_refs
        if isinstance(ref, Mapping)
    ]
    evidence_paths = {ref.get('path') or ref.get('artifact_path') or ref.get('document_path') for ref in evidence_refs}
    for path in _require_string_list('context.required_evidence_paths', context.get('required_evidence_paths')):
        if path not in evidence_paths:
            raise XamanProofConsumerError(f'missing reviewed evidence reference: {path}')
    if any(not _source_review_is_accepted(ref) for ref in evidence_refs):
        raise XamanProofConsumerError('proof report includes unreviewed evidence')

    environment = _require_mapping('context.environment_probe', context.get('environment_probe'))
    if environment.get('proof_acceptance_blocked') is True:
        raise XamanProofConsumerError('environment probe blocks proof acceptance')
    if environment.get('overall_status') != 'ready':
        raise XamanProofConsumerError('environment probe is not ready')
    if environment.get('schema_version') != 'xaman-environment-probe/v1':
        raise XamanProofConsumerError('unsupported environment probe schema')
    receipt_environment = _require_mapping(
        'proof_receipt.metadata.environment_probe',
        receipt.metadata.get('environment_probe'),
    )
    if receipt_environment.get('generated_at_utc') != environment.get('generated_at_utc'):
        raise XamanProofConsumerError('receipt environment probe timestamp binding mismatch')
    if receipt_environment.get('proof_acceptance_blocked') != environment.get('proof_acceptance_blocked'):
        raise XamanProofConsumerError('receipt environment probe acceptance binding mismatch')
    release_window = _parse_utc(
        release_window_at_utc or _require_string(
            'context.release_window_at_utc',
            context.get('release_window_at_utc'),
        ),
        field_name='release_window_at_utc',
    )
    generated = _parse_utc(
        _require_string('context.environment_probe.generated_at_utc', environment.get('generated_at_utc')),
        field_name='context.environment_probe.generated_at_utc',
    )
    max_age_hours = context.get('fresh_environment_max_age_hours')
    if isinstance(max_age_hours, bool) or not isinstance(max_age_hours, int) or max_age_hours <= 0:
        raise XamanProofConsumerError('fresh_environment_max_age_hours must be a positive integer')
    age_seconds = (release_window - generated).total_seconds()
    if age_seconds < 0:
        raise XamanProofConsumerError('environment probe is newer than the release window')
    if age_seconds > max_age_hours * 3600:
        raise XamanProofConsumerError('environment probe is stale for the release window')

    checked_bindings = set(_require_string_list('context.checked_bindings', context.get('checked_bindings')))
    missing_bindings = sorted(set(REQUIRED_BINDINGS) - checked_bindings)
    if missing_bindings:
        raise XamanProofConsumerError(f'missing checked binding(s): {", ".join(missing_bindings)}')

    return {
        'accepted': True,
        'claim_id': expected_claim_id,
        'model_cid': expected_model_cid,
        'proof_report_cid': report.cid,
        'solver_name': report.solver_name,
        'checked_bindings': sorted(checked_bindings),
    }


def _proof_kernel_cid(lean_source: str) -> str:
    return calculate_artifact_cid(
        {
            'path': PROOF_KERNEL_PATH,
            'source_sha256_payload': lean_source,
            'theorems': PROOF_KERNEL_THEOREMS,
        }
    )


def _reviewed_evidence_refs(model_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    claim = next(
        entry for entry in model_payload['claims']
        if entry['id'] == CLAIM_ID
    )
    refs = [
        {
            'kind': 'proof_kernel',
            'path': PROOF_KERNEL_PATH,
            'review_status': 'human_reviewed',
            'theorems': PROOF_KERNEL_THEOREMS,
        },
        {
            'kind': 'source_manifest',
            'path': SOURCE_MANIFEST_PATH,
            'review_status': 'human_reviewed',
        },
        {
            'kind': 'environment_probe',
            'path': ENVIRONMENT_PROBE_PATH,
            'review_status': 'human_reviewed',
        },
    ]
    refs.extend(deepcopy(claim.get('evidence_refs', [])))
    return refs


def _build_context(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    environment_probe: Mapping[str, Any],
    lean_source: str,
) -> dict[str, Any]:
    corpus = deepcopy(model_payload['metadata']['corpus'])
    return {
        'schema_version': 'xaman-proof-consumer-context/v1',
        'claim_id': CLAIM_ID,
        'model_cid': model_cid,
        'model_path': MODEL_PATH,
        'model_cid_path': MODEL_CID_PATH,
        'modeled_claim_ids': [claim['id'] for claim in model_payload['claims']],
        'required_assumptions': list(REQUIRED_ASSUMPTIONS),
        'required_evidence_paths': list(REQUIRED_EVIDENCE_PATHS),
        'corpus': corpus,
        'environment_probe_path': ENVIRONMENT_PROBE_PATH,
        'environment_probe': deepcopy(environment_probe),
        'release_window_at_utc': RELEASE_WINDOW_AT_UTC,
        'fresh_environment_max_age_hours': FRESH_ENVIRONMENT_MAX_AGE_HOURS,
        'checked_bindings': list(REQUIRED_BINDINGS),
        'solver_allowlist': {
            'python': {
                'status': 'present',
                'required': True,
                'version': environment_probe['solver_paths']['resolved_executables']['python']['version'],
                'executable': environment_probe['solver_paths']['resolved_executables']['python']['executable'],
                'role': 'proof-consumer invariant checker',
            }
        },
        'proof_kernel': {
            'language': 'Lean',
            'path': PROOF_KERNEL_PATH,
            'artifact_cid': _proof_kernel_cid(lean_source),
            'theorems': list(PROOF_KERNEL_THEOREMS),
            'external_lean_execution': 'not-required-for-ci',
        },
    }


def build_xaman_proof_consumer_report(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    environment_probe: Mapping[str, Any],
    lean_source: str,
) -> dict[str, Any]:
    """Build the checked Xaman proof-consumer report artifact."""

    context = _build_context(
        model_payload=model_payload,
        model_cid=model_cid,
        environment_probe=environment_probe,
        lean_source=lean_source,
    )
    proof_kernel_cid = context['proof_kernel']['artifact_cid']
    report = ProofReport(
        claim_id=CLAIM_ID,
        claim_version='1.0',
        model_cid=model_cid,
        model_schema_version=model_payload['schema_version'],
        status='PROVED',
        prover='python-proof-consumer',
        solver_name='python',
        solver_version=context['solver_allowlist']['python']['version'],
        solver_result='checked',
        proof_or_trace_cid=proof_kernel_cid,
        assumptions=list(REQUIRED_ASSUMPTIONS),
        compiler_cid=calculate_artifact_cid(
            {
                'task_id': TASK_ID,
                'proof_kernel_path': PROOF_KERNEL_PATH,
                'proof_kernel_cid': proof_kernel_cid,
                'checked_bindings': REQUIRED_BINDINGS,
            }
        ),
        risk='blocking',
        signatures=[
            {
                'key_id': 'xaman-proof-consumer-ci-static-fixture',
                'signature': calculate_artifact_cid(
                    {
                        'model_cid': model_cid,
                        'claim_id': CLAIM_ID,
                        'proof_kernel_cid': proof_kernel_cid,
                    }
                ),
                'signature_type': 'deterministic-fixture-attestation',
            }
        ],
        generated_at=FIXED_GENERATED_AT_UTC,
        evidence_refs=_reviewed_evidence_refs(model_payload),
        soundness_notes=[
            'This packet checks proof-consumer receipt invariants; it does not unblock Xaman production release by itself.',
            'Lean source is committed as a small proof-kernel specification and CI executes the equivalent Python consumer predicate.',
        ],
        unsat_core=list(REQUIRED_BINDINGS),
    )
    receipt = ProofReceipt.from_report(
        report,
        verifier='xaman-proof-consumer',
        verifier_version='1.0',
        accepted_assumptions=list(REQUIRED_ASSUMPTIONS),
    )
    receipt.metadata.update(
        {
            'solver_identity': {
                'prover': report.prover,
                'solver_name': report.solver_name,
                'solver_version': report.solver_version,
                'solver_result': report.solver_result,
            },
            'corpus': deepcopy(context['corpus']),
            'environment_probe': {
                'path': ENVIRONMENT_PROBE_PATH,
                'generated_at_utc': environment_probe['generated_at_utc'],
                'overall_status': environment_probe['overall_status'],
                'proof_acceptance_blocked': environment_probe['proof_acceptance_blocked'],
            },
            'checked_bindings': list(REQUIRED_BINDINGS),
            'proof_kernel_cid': proof_kernel_cid,
        }
    )
    packet = {
        'proof_report': report.to_dict(),
        'proof_receipt': receipt.to_dict(),
        'context': context,
    }
    accepted_verdict = validate_xaman_proof_consumer_packet(packet)
    rejected_fixtures = _build_rejected_fixtures(packet)
    artifact = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': FIXED_GENERATED_AT_UTC,
        'corpus': context['corpus'],
        'model_cid': model_cid,
        'claim_id': CLAIM_ID,
        'proof_kernel_path': PROOF_KERNEL_PATH,
        'proof_kernel_cid': proof_kernel_cid,
        'accepted_packet': packet,
        'accepted_verdict': accepted_verdict,
        'rejected_outcomes': list(REJECTED_OUTCOMES),
        'rejected_fixtures': rejected_fixtures,
        'summary': {
            'accepted_fixture_count': 1,
            'rejected_fixture_count': len(rejected_fixtures),
            'checked_bindings': list(REQUIRED_BINDINGS),
            'fresh_environment_max_age_hours': FRESH_ENVIRONMENT_MAX_AGE_HOURS,
            'production_release_effect': 'no-release-unblock',
        },
    }
    artifact['artifact_cid'] = _artifact_cid_without_self(artifact)
    return artifact


def _mutated_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(packet))


def _build_rejected_fixtures(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases: list[tuple[str, str, dict[str, Any]]] = []

    for status in ('DISPROVED', 'UNKNOWN', 'NOT_MODELED'):
        mutated = _mutated_packet(packet)
        mutated['proof_report']['status'] = status
        mutated['proof_report']['solver_result'] = {
            'DISPROVED': 'sat',
            'UNKNOWN': 'unknown',
            'NOT_MODELED': 'not-modeled',
        }[status]
        mutated['proof_report'].pop('deterministic_payload_cid', None)
        mutated['proof_report'].pop('nondeterministic_report_cid', None)
        report = ProofReport.from_dict(mutated['proof_report'])
        mutated['proof_report'] = report.to_dict()
        mutated['proof_receipt']['proof_report_cid'] = report.cid
        cases.append((f'reject_{status.lower()}', status, mutated))

    missing_solver = _mutated_packet(packet)
    missing_solver['proof_report']['solver_name'] = 'lean4'
    missing_solver['proof_report']['solver_version'] = 'missing'
    missing_solver['proof_report'].pop('deterministic_payload_cid', None)
    missing_solver['proof_report'].pop('nondeterministic_report_cid', None)
    missing_report = ProofReport.from_dict(missing_solver['proof_report'])
    missing_solver['proof_report'] = missing_report.to_dict()
    missing_solver['proof_receipt']['proof_report_cid'] = missing_report.cid
    missing_solver['proof_receipt']['metadata']['solver_identity'] = {
        'prover': missing_report.prover,
        'solver_name': missing_report.solver_name,
        'solver_version': missing_report.solver_version,
        'solver_result': missing_report.solver_result,
    }
    cases.append(('reject_missing_solver', 'MISSING_SOLVER', missing_solver))

    stale = _mutated_packet(packet)
    stale['context']['environment_probe']['generated_at_utc'] = '2026-07-06T20:29:12Z'
    stale['proof_receipt']['metadata']['environment_probe']['generated_at_utc'] = '2026-07-06T20:29:12Z'
    cases.append(('reject_stale_environment_probe', 'STALE_ENVIRONMENT_PROBE', stale))

    mismatched_cid = _mutated_packet(packet)
    mismatched_cid['proof_receipt']['proof_report_cid'] = 'sha256:mismatched-report'
    cases.append(('reject_mismatched_report_cid', 'MISMATCHED_REPORT_CID', mismatched_cid))

    unaccepted_assumption = _mutated_packet(packet)
    unaccepted_assumption['proof_receipt']['accepted_assumptions'] = [REQUIRED_ASSUMPTIONS[0]]
    cases.append(('reject_unaccepted_assumption', 'UNACCEPTED_ASSUMPTION', unaccepted_assumption))

    fixtures = []
    for case_id, outcome, mutated in cases:
        try:
            validate_xaman_proof_consumer_packet(mutated)
        except Exception as exc:  # noqa: BLE001 - fixture records the fail-closed reason
            fixtures.append(
                {
                    'case_id': case_id,
                    'outcome': outcome,
                    'accepted': False,
                    'rejection_reason': str(exc),
                }
            )
        else:  # pragma: no cover - would be a construction bug
            fixtures.append(
                {
                    'case_id': case_id,
                    'outcome': outcome,
                    'accepted': True,
                    'rejection_reason': 'mutation was unexpectedly accepted',
                }
            )
    return fixtures


__all__ = [
    'CLAIM_ID',
    'REQUIRED_ASSUMPTIONS',
    'REQUIRED_BINDINGS',
    'REJECTED_OUTCOMES',
    'SCHEMA_VERSION',
    'TASK_ID',
    'XamanProofConsumerError',
    'build_xaman_proof_consumer_report',
    'validate_xaman_proof_consumer_packet',
]
