"""XRPL Testnet scoped assurance verdict aggregation.

This module rolls up the Testnet-only Xaman evidence into a governance verdict.
It does not create new proof evidence; it binds existing artifacts, preserves
their fail-closed statuses, and emits one of the accepted scoped verdict values.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid

TASK_ID = 'PORTAL-CXTP-139'
BUNDLE_SCHEMA_VERSION = 'xaman-testnet-assurance-bundle/v1'
VERDICT_SCHEMA_VERSION = 'xaman-testnet-assurance-verdict/v1'
FIXED_GENERATED_AT_UTC = '2026-07-11T00:00:00Z'

TESTNET_ROOT = 'security_ir_artifacts/corpora/xaman-app/testnet'
MODEL_PATH = f'{TESTNET_ROOT}/security-model-ir.json'
MODEL_CID_PATH = f'{TESTNET_ROOT}/security-model-ir.cid'
ASSUMPTIONS_PATH = f'{TESTNET_ROOT}/assumptions.json'
CLAIM_TRACE_MAP_PATH = f'{TESTNET_ROOT}/claim-trace-map.json'
SMT_REPORT_PATH = f'{TESTNET_ROOT}/proof-reports/z3-cvc5-differential.json'
APALACHE_REPORT_PATH = f'{TESTNET_ROOT}/tla/apalache-report.json'
PROTOCOL_REPORT_PATH = f'{TESTNET_ROOT}/protocol/protocol-report.json'
LEAN_REPORT_PATH = f'{TESTNET_ROOT}/proof-kernel/lean-report.json'
COQ_DECISION_PATH = f'{TESTNET_ROOT}/coq-coverage-decision.json'
FUZZ_REPORT_PATH = f'{TESTNET_ROOT}/fuzz/fuzz-report.json'
LEANSTRAL_AUDIT_PATH = f'{TESTNET_ROOT}/leanstral-candidate-audit.json'
BUNDLE_PATH = f'{TESTNET_ROOT}/assurance-bundle.json'
VERDICT_PATH = f'{TESTNET_ROOT}/assurance-verdict.json'
VERDICT_DOC_PATH = 'docs/security_verification/xaman_xrpl_testnet_assurance_verdict.md'

ALLOWED_VERDICTS = (
    'TESTNET_SCOPE_ASSURED',
    'TESTNET_SCOPE_NOT_SECURE',
    'TESTNET_SCOPE_INCONCLUSIVE',
)


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    for key in ('artifact_cid', 'report_cid'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return calculate_artifact_cid(payload)


def _cid_without(payload: Mapping[str, Any], key: str) -> str:
    return calculate_artifact_cid(
        {
            item_key: item_value
            for item_key, item_value in payload.items()
            if item_key != key
        }
    )


def _artifact_entry(kind: str, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    entry = {
        'kind': kind,
        'path': path,
        'schema_version': payload.get('schema_version'),
        'task_id': payload.get('task_id'),
        'artifact_cid': _artifact_cid(payload),
    }
    for key in ('overall_status', 'security_decision', 'testnet_assurance_blocked'):
        if key in payload:
            entry[key] = payload[key]
    model = payload.get('model')
    if isinstance(model, Mapping) and isinstance(model.get('cid'), str):
        entry['model_cid'] = model['cid']
    elif isinstance(payload.get('model_cid'), str):
        entry['model_cid'] = payload['model_cid']
    return entry


def _blocking_assumptions(assumptions_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    assumptions = assumptions_payload.get('assumptions', [])
    return [
        {
            'id': assumption['id'],
            'owner': assumption.get('owner'),
            'status': assumption.get('status'),
            'description': assumption.get('description'),
            'required_evidence_to_clear': deepcopy(
                assumption.get('required_evidence_to_clear', [])
            ),
            'evidence_expires_at': assumption.get('evidence_expires_at'),
        }
        for assumption in assumptions
        if assumption.get('status') == 'BLOCKING'
    ]


def _claim_summary(
    model_payload: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
) -> dict[str, Any]:
    claims = list(model_payload.get('claims', []))
    smt_claims = list(smt_report.get('claims', []))
    model_status_counts = Counter(str(claim.get('status')) for claim in claims)
    smt_result_counts = Counter(str(claim.get('result')) for claim in smt_claims)
    classification_counts = Counter(
        str(claim.get('worker_classification')) for claim in smt_claims
    )
    not_modeled = [
        claim['id']
        for claim in claims
        if claim.get('status') == 'NOT_MODELED'
    ]
    blocking_not_modeled_boundary = [
        claim['id']
        for claim in claims
        if claim.get('status') == 'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY'
    ]
    protocol_not_modeled = list(
        protocol_report.get('coverage_decision', {}).get('not_modeled_claim_ids', [])
    )
    return {
        'claim_count': len(claims),
        'model_status_counts': dict(sorted(model_status_counts.items())),
        'smt_result_counts': dict(sorted(smt_result_counts.items())),
        'smt_worker_classification_counts': dict(sorted(classification_counts.items())),
        'smt_counterexample_claim_ids': [
            claim['claim_id']
            for claim in smt_claims
            if claim.get('result') == 'COUNTEREXAMPLE'
        ],
        'not_modeled_claim_ids': not_modeled,
        'blocking_not_modeled_boundary_claim_ids': blocking_not_modeled_boundary,
        'protocol_not_modeled_claim_ids': protocol_not_modeled,
    }


def _lane_summary(
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    lean_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
) -> dict[str, Any]:
    smt_claims = list(smt_report.get('claims', []))
    protocol_blockers = list(protocol_report.get('blockers', []))
    apalache_summary = apalache_report.get('summary', {})
    fuzz_summary = fuzz_report.get('summary', {})
    return {
        'smt_z3_cvc5': {
            'path': SMT_REPORT_PATH,
            'overall_status': smt_report.get('overall_status'),
            'security_decision': smt_report.get('security_decision'),
            'counterexample_count': sum(
                1 for claim in smt_claims if claim.get('result') == 'COUNTEREXAMPLE'
            ),
            'testnet_assurance_blocked': smt_report.get('testnet_assurance_blocked'),
        },
        'apalache': {
            'path': APALACHE_REPORT_PATH,
            'overall_status': apalache_report.get('overall_status'),
            'security_decision': apalache_report.get('security_decision'),
            'checked_invariant_count': apalache_summary.get('checked_invariant_count'),
            'unresolved_required_assumption_count': apalache_summary.get(
                'unresolved_required_assumption_count'
            ),
            'testnet_assurance_blocked': apalache_report.get('testnet_assurance_blocked'),
        },
        'protocol': {
            'path': PROTOCOL_REPORT_PATH,
            'overall_status': protocol_report.get('overall_status'),
            'security_decision': protocol_report.get('security_decision'),
            'blocker_codes': [blocker.get('code') for blocker in protocol_blockers],
            'not_modeled_claim_count': len(
                protocol_report.get('coverage_decision', {}).get(
                    'not_modeled_claim_ids',
                    [],
                )
            ),
            'testnet_assurance_blocked': protocol_report.get('testnet_assurance_blocked'),
        },
        'lean': {
            'path': LEAN_REPORT_PATH,
            'overall_status': lean_report.get('overall_status'),
            'security_decision': lean_report.get('security_decision'),
            'formalized_invariant_only': True,
            'testnet_assurance_blocked': lean_report.get('testnet_assurance_blocked'),
        },
        'coq': {
            'path': COQ_DECISION_PATH,
            'overall_status': coq_decision.get('overall_status'),
            'security_decision': coq_decision.get('security_decision'),
            'decision': coq_decision.get('decision'),
            'required_by_reviewed_threat_model': coq_decision.get(
                'coq_required_by_reviewed_threat_model'
            ),
            'testnet_assurance_blocked': coq_decision.get('testnet_assurance_blocked'),
        },
        'fuzz': {
            'path': FUZZ_REPORT_PATH,
            'overall_status': fuzz_summary.get('overall_status'),
            'security_decision': fuzz_summary.get('security_decision'),
            'counterexample_count': fuzz_summary.get('counterexample_count'),
            'failed_case_count': fuzz_summary.get('failed_case_count'),
            'fuzzer_crash_count': fuzz_summary.get('fuzzer_crash_count'),
            'acceptance_gates': deepcopy(fuzz_report.get('acceptance_gates', {})),
        },
    }


def _owner_actions(
    assumptions_payload: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
) -> list[dict[str, Any]]:
    actions = [
        {
            'source': ASSUMPTIONS_PATH,
            'assumption_id': assumption['id'],
            'owner': assumption.get('owner'),
            'required_evidence_to_clear': deepcopy(
                assumption.get('required_evidence_to_clear', [])
            ),
        }
        for assumption in _blocking_assumptions(assumptions_payload)
    ]
    for blocker in protocol_report.get('blockers', []):
        code = blocker.get('code')
        if code == 'PROVERIF_MODEL_MISSING':
            actions.append(
                {
                    'source': PROTOCOL_REPORT_PATH,
                    'owner': 'protocol-verification',
                    'required_evidence_to_clear': [
                        'Add a reviewed ProVerif projection for the Testnet payload protocol.',
                        'Run ProVerif with pinned executable/version/digest and attach the accepted report.',
                    ],
                }
            )
        elif code == 'TAMARIN_CHECK_NOT_RUN':
            actions.append(
                {
                    'source': PROTOCOL_REPORT_PATH,
                    'owner': 'protocol-verification',
                    'required_evidence_to_clear': [
                        'Run the pinned Tamarin model against an accepted Maude runtime.',
                        'Record the command, version, executable digest, and accepted lemma results.',
                    ],
                }
            )
    if coq_decision.get('decision') == 'required_missing_artifact':
        actions.append(
            {
                'source': COQ_DECISION_PATH,
                'owner': 'formal-methods',
                'required_evidence_to_clear': [
                    'Provide security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.v.',
                    'Run coqc and bind the checked independent-kernel artifact to the Testnet model CID.',
                ],
            }
        )
    return actions


def _blockers(
    *,
    assumptions_payload: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    model_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    claims = list(smt_report.get('claims', []))
    counterexample_count = sum(
        1 for claim in claims if claim.get('result') == 'COUNTEREXAMPLE'
    )
    blocking_assumptions = _blocking_assumptions(assumptions_payload)
    not_modeled_claim_ids = [
        claim['id']
        for claim in model_payload.get('claims', [])
        if claim.get('status') == 'NOT_MODELED'
    ]
    blockers = []
    if counterexample_count:
        blockers.append(
            {
                'code': 'SMT_COUNTEREXAMPLES_FOUND',
                'severity': 'blocking',
                'source': SMT_REPORT_PATH,
                'count': counterexample_count,
            }
        )
    if blocking_assumptions:
        blockers.append(
            {
                'code': 'BLOCKING_TESTNET_ASSUMPTIONS',
                'severity': 'blocking',
                'source': ASSUMPTIONS_PATH,
                'count': len(blocking_assumptions),
            }
        )
    unresolved = apalache_report.get('summary', {}).get('unresolved_required_assumption_count', 0)
    if unresolved:
        blockers.append(
            {
                'code': 'UNRESOLVED_CONCURRENCY_ASSUMPTIONS',
                'severity': 'blocking',
                'source': APALACHE_REPORT_PATH,
                'count': unresolved,
            }
        )
    protocol_blockers = list(protocol_report.get('blockers', []))
    if protocol_blockers:
        blockers.append(
            {
                'code': 'REQUIRED_PROTOCOL_LANE_UNAVAILABLE',
                'severity': 'blocking',
                'source': PROTOCOL_REPORT_PATH,
                'count': len(protocol_blockers),
                'blocker_codes': [blocker.get('code') for blocker in protocol_blockers],
            }
        )
    if coq_decision.get('testnet_assurance_blocked'):
        blockers.append(
            {
                'code': 'INDEPENDENT_COQ_KERNEL_MISSING',
                'severity': 'blocking',
                'source': COQ_DECISION_PATH,
                'decision': coq_decision.get('decision'),
            }
        )
    if not_modeled_claim_ids:
        blockers.append(
            {
                'code': 'NOT_MODELED_TESTNET_CLAIMS',
                'severity': 'blocking',
                'source': MODEL_PATH,
                'count': len(not_modeled_claim_ids),
                'claim_ids': not_modeled_claim_ids,
            }
        )
    blockers.append(
        {
            'code': 'PRODUCTION_SECURITY_RESULT_EXCLUDED',
            'severity': 'scope',
            'source': MODEL_PATH,
            'message': 'The Testnet evidence cannot approve production Xaman wallet security.',
        }
    )
    return blockers


def _derive_verdict(
    *,
    smt_report: Mapping[str, Any],
    blockers: Sequence[Mapping[str, Any]],
) -> str:
    if any(
        claim.get('result') == 'COUNTEREXAMPLE'
        for claim in smt_report.get('claims', [])
    ):
        return 'TESTNET_SCOPE_NOT_SECURE'
    blocking_codes = {
        blocker.get('code')
        for blocker in blockers
        if blocker.get('severity') == 'blocking'
    }
    if blocking_codes:
        return 'TESTNET_SCOPE_INCONCLUSIVE'
    return 'TESTNET_SCOPE_ASSURED'


def build_xaman_testnet_assurance_bundle(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    assumptions_payload: Mapping[str, Any],
    claim_trace_map: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    lean_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    leanstral_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the deterministic Testnet evidence bundle."""

    blockers = _blockers(
        assumptions_payload=assumptions_payload,
        smt_report=smt_report,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        coq_decision=coq_decision,
        model_payload=model_payload,
    )
    bundle = {
        'schema_version': BUNDLE_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': FIXED_GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'scope': {
            'network': 'XRPL Testnet',
            'network_id': 1,
            'production_security_result': False,
            'statement': (
                'This bundle is limited to the reviewed XRPL Testnet verifier APK, '
                'emulator trial, formalized model, and pinned evidence artifacts. '
                'It is not a production-security result.'
            ),
        },
        'decision_vocabulary': list(ALLOWED_VERDICTS),
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'cid': model_cid,
            'model_id': model_payload.get('model_id'),
            'schema_version': model_payload.get('schema_version'),
            'claim_count': len(model_payload.get('claims', [])),
            'assumption_count': len(model_payload.get('assumptions', [])),
        },
        'evidence_artifacts': [
            _artifact_entry('testnet_security_model_ir', MODEL_PATH, model_payload),
            _artifact_entry('testnet_assumptions', ASSUMPTIONS_PATH, assumptions_payload),
            _artifact_entry('claim_trace_map', CLAIM_TRACE_MAP_PATH, claim_trace_map),
            _artifact_entry('smt_z3_cvc5_differential', SMT_REPORT_PATH, smt_report),
            _artifact_entry('tla_apalache', APALACHE_REPORT_PATH, apalache_report),
            _artifact_entry('protocol_tamarin_proverif', PROTOCOL_REPORT_PATH, protocol_report),
            _artifact_entry('lean_kernel', LEAN_REPORT_PATH, lean_report),
            _artifact_entry('coq_coverage_decision', COQ_DECISION_PATH, coq_decision),
            _artifact_entry('fuzz_campaign', FUZZ_REPORT_PATH, fuzz_report),
            _artifact_entry('leanstral_candidate_audit', LEANSTRAL_AUDIT_PATH, leanstral_audit),
        ],
        'claim_summary': _claim_summary(model_payload, smt_report, protocol_report),
        'lane_summary': _lane_summary(
            smt_report,
            apalache_report,
            protocol_report,
            lean_report,
            coq_decision,
            fuzz_report,
        ),
        'blocking_assumptions': _blocking_assumptions(assumptions_payload),
        'blockers': blockers,
        'owner_actions_required_to_advance': _owner_actions(
            assumptions_payload,
            protocol_report,
            coq_decision,
        ),
    }
    bundle['artifact_cid'] = _cid_without(bundle, 'artifact_cid')
    return bundle


def build_xaman_testnet_assurance_verdict(
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the scoped verdict from a generated bundle."""

    smt_lane = bundle['lane_summary']['smt_z3_cvc5']
    verdict = _derive_verdict(
        smt_report={
            'claims': [
                {'result': 'COUNTEREXAMPLE'}
                for _ in range(int(smt_lane.get('counterexample_count') or 0))
            ]
        },
        blockers=bundle.get('blockers', []),
    )
    required_actions = list(bundle.get('owner_actions_required_to_advance', []))
    payload = {
        'schema_version': VERDICT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': FIXED_GENERATED_AT_UTC,
        'verdict': verdict,
        'allowed_verdicts': list(ALLOWED_VERDICTS),
        'bundle': {
            'path': BUNDLE_PATH,
            'artifact_cid': bundle['artifact_cid'],
            'schema_version': bundle['schema_version'],
        },
        'not_a_production_security_result': True,
        'production_security_statement': (
            'This verdict is scoped only to the reviewed XRPL Testnet evidence. '
            'It does not approve, certify, or reject the production Xaman wallet, '
            'production backend, production XRPL behavior, or real-asset custody.'
        ),
        'rationale': {
            'primary_reason': (
                'The Z3/CVC5 Testnet lane reports counterexamples for every frozen '
                'Testnet claim, so the scoped Testnet verdict is not secure.'
            ),
            'counterexample_count': smt_lane.get('counterexample_count'),
            'blocking_assumption_count': len(bundle.get('blocking_assumptions', [])),
            'blocker_codes': [blocker.get('code') for blocker in bundle.get('blockers', [])],
        },
        'precise_evidence_or_owner_action_required_to_advance': required_actions,
        'next_decision_rule': (
            'Advance only after all blocking owner actions are satisfied, the model CID '
            'is regenerated, Z3/CVC5 no longer emit counterexamples for required claims, '
            'Tamarin/ProVerif and required Coq evidence are accepted, and a new bundle '
            'is issued with the same non-production scope statement.'
        ),
    }
    payload['artifact_cid'] = _cid_without(payload, 'artifact_cid')
    return payload


def render_xaman_testnet_assurance_verdict_markdown(
    bundle: Mapping[str, Any],
    verdict: Mapping[str, Any],
) -> str:
    """Render the human-readable verdict document."""

    lane = bundle['lane_summary']
    lines = [
        '# Xaman XRPL Testnet Assurance Verdict',
        '',
        f'Task: `{TASK_ID}`',
        '',
        f'Verdict: `{verdict["verdict"]}`',
        '',
        'This is not a production-security result. It covers only the reviewed XRPL '
        'Testnet verifier APK, emulator trial, formalized model, solver reports, and '
        'fuzz artifacts bound in the Testnet assurance bundle.',
        '',
        '## Bound Artifacts',
        '',
        f'- Bundle: `{BUNDLE_PATH}`',
        f'- Bundle CID: `{bundle["artifact_cid"]}`',
        f'- Verdict: `{VERDICT_PATH}`',
        f'- Verdict CID: `{verdict["artifact_cid"]}`',
        f'- Model CID: `{bundle["model"]["cid"]}`',
        '',
        '## Basis',
        '',
        f'- SMT Z3/CVC5: `{lane["smt_z3_cvc5"]["security_decision"]}` with '
        f'`{lane["smt_z3_cvc5"]["counterexample_count"]}` counterexample classifications.',
        f'- Apalache: `{lane["apalache"]["security_decision"]}` with '
        f'`{lane["apalache"]["unresolved_required_assumption_count"]}` unresolved required assumptions.',
        f'- Protocol lane: `{lane["protocol"]["security_decision"]}`; blockers are '
        f'`{", ".join(lane["protocol"]["blocker_codes"])}`.',
        f'- Lean: `{lane["lean"]["security_decision"]}` for formalized invariants only.',
        f'- Coq: `{lane["coq"]["security_decision"]}`.',
        f'- Fuzzing: `{lane["fuzz"]["security_decision"]}` with bounded generated coverage.',
        '',
        '## Required Evidence Or Owner Action',
        '',
    ]
    for action in verdict['precise_evidence_or_owner_action_required_to_advance']:
        owner = action.get('owner', 'unassigned')
        source = action.get('source')
        requirement = '; '.join(action.get('required_evidence_to_clear', []))
        assumption = action.get('assumption_id')
        prefix = f'- `{owner}`'
        if assumption:
            prefix += f' for `{assumption}`'
        lines.append(f'{prefix}: {requirement} Source: `{source}`.')
    lines.extend(
        [
            '',
            '## Decision Rule',
            '',
            verdict['next_decision_rule'],
            '',
            'Allowed verdict values remain exactly `TESTNET_SCOPE_ASSURED`, '
            '`TESTNET_SCOPE_NOT_SECURE`, or `TESTNET_SCOPE_INCONCLUSIVE`.',
            '',
        ]
    )
    return '\n'.join(lines)


__all__ = [
    'ALLOWED_VERDICTS',
    'APALACHE_REPORT_PATH',
    'ASSUMPTIONS_PATH',
    'BUNDLE_PATH',
    'BUNDLE_SCHEMA_VERSION',
    'CLAIM_TRACE_MAP_PATH',
    'COQ_DECISION_PATH',
    'FUZZ_REPORT_PATH',
    'LEAN_REPORT_PATH',
    'LEANSTRAL_AUDIT_PATH',
    'MODEL_CID_PATH',
    'MODEL_PATH',
    'PROTOCOL_REPORT_PATH',
    'SMT_REPORT_PATH',
    'TASK_ID',
    'VERDICT_DOC_PATH',
    'VERDICT_PATH',
    'VERDICT_SCHEMA_VERSION',
    'build_xaman_testnet_assurance_bundle',
    'build_xaman_testnet_assurance_verdict',
    'render_xaman_testnet_assurance_verdict_markdown',
]
