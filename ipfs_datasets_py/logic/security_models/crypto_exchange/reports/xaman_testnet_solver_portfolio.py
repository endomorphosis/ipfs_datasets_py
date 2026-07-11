"""Reconciled multi-solver portfolio for the frozen Xaman Testnet model."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-147'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
MANIFEST_SCHEMA_VERSION = 'xaman-testnet-solver-portfolio-manifest/v1'
REPORT_SCHEMA_VERSION = 'xaman-testnet-solver-portfolio-report/v1'

TESTNET_ROOT = 'security_ir_artifacts/corpora/xaman-app/testnet'
XAMAN_ROOT = 'security_ir_artifacts/corpora/xaman-app'
MODEL_PATH = f'{TESTNET_ROOT}/security-model-ir.json'
MODEL_CID_PATH = f'{TESTNET_ROOT}/security-model-ir.cid'
ASSUMPTIONS_PATH = f'{TESTNET_ROOT}/assumptions.json'
CLAIM_TRACE_MAP_PATH = f'{TESTNET_ROOT}/claim-trace-map.json'
PROOF_WORKER_LOCK_PATH = f'{TESTNET_ROOT}/proof-worker-lock.json'
CVC5_RUNNER_REPORT_PATH = f'{TESTNET_ROOT}/cvc5-runner-report.json'
SMT_REPORT_PATH = f'{TESTNET_ROOT}/proof-reports/z3-cvc5-differential.json'
APALACHE_REPORT_PATH = f'{TESTNET_ROOT}/tla/apalache-report.json'
PROTOCOL_REPORT_PATH = f'{TESTNET_ROOT}/protocol/protocol-report.json'
LEAN_REPORT_PATH = f'{TESTNET_ROOT}/proof-kernel/lean-report.json'
COQ_DECISION_PATH = f'{TESTNET_ROOT}/coq-coverage-decision.json'
FUZZ_REPORT_PATH = f'{TESTNET_ROOT}/fuzz/fuzz-report.json'
FUZZ_COUNTEREXAMPLE_MANIFEST_PATH = f'{TESTNET_ROOT}/fuzz/counterexamples/manifest.json'
SOURCE_MANIFEST_PATH = f'{XAMAN_ROOT}/source-manifest.json'
SOURCE_CLAIM_MAP_PATH = f'{XAMAN_ROOT}/source-claim-map.json'
XRPL_TRANSACTION_COVERAGE_PATH = f'{XAMAN_ROOT}/xrpl-transaction-coverage.json'
DISPROOF_VECTORS_PATH = f'{XAMAN_ROOT}/disproof-vectors.json'

PORTFOLIO_MANIFEST_PATH = f'{TESTNET_ROOT}/solver-portfolio-manifest.json'
PORTFOLIO_REPORT_PATH = f'{TESTNET_ROOT}/solver-portfolio-report.json'
PORTFOLIO_DOC_PATH = 'docs/security_verification/xaman_testnet_solver_portfolio.md'

LANE_ORDER = (
    'z3_cvc5_differential',
    'apalache_state',
    'tamarin_protocol',
    'proverif_protocol',
    'lean_kernel',
    'rocq_kernel',
    'fuzz_consumption',
)

FAIL_CLOSED_STATUSES = {
    'COUNTEREXAMPLE',
    'DISAGREE',
    'FAILED',
    'INCOMPLETE',
    'NOT_RUN',
    'REQUIRED_UNAVAILABLE',
    'REQUIRED_MISSING_ARTIFACT',
    'TIMEOUT',
    'UNKNOWN',
}


def build_xaman_testnet_solver_portfolio_manifest(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    assumptions_payload: Mapping[str, Any],
    claim_trace_map: Mapping[str, Any],
    proof_worker_lock: Mapping[str, Any],
    cvc5_runner_report: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    lean_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
    source_manifest: Mapping[str, Any] | None = None,
    source_claim_map: Mapping[str, Any] | None = None,
    xrpl_transaction_coverage: Mapping[str, Any] | None = None,
    disproof_vectors: Mapping[str, Any] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Build the deterministic portfolio manifest for all solver lanes."""

    _validate_model_bindings(
        model_cid=model_cid,
        model_payload=model_payload,
        assumptions_payload=assumptions_payload,
        claim_trace_map=claim_trace_map,
        proof_worker_lock=proof_worker_lock,
        cvc5_runner_report=cvc5_runner_report,
        smt_report=smt_report,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        lean_report=lean_report,
        coq_decision=coq_decision,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
    )
    claims = list(model_payload.get('claims', []))
    claim_ids = [claim['id'] for claim in claims]
    source = _source_binding(model_payload, source_manifest, source_claim_map)
    lane_inventory = _lane_inventory(
        proof_worker_lock=proof_worker_lock,
        cvc5_runner_report=cvc5_runner_report,
        smt_report=smt_report,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        lean_report=lean_report,
        coq_decision=coq_decision,
        fuzz_report=fuzz_report,
        repo_root=repo_root,
    )
    claim_evidence = [
        _claim_manifest_entry(claim, model_cid=model_cid)
        for claim in claims
    ]
    dependency_artifacts = [
        _artifact_entry('security_model_ir', MODEL_PATH, model_payload, model_cid=model_cid),
        _artifact_entry('assumptions', ASSUMPTIONS_PATH, assumptions_payload, model_cid=model_cid),
        _artifact_entry('claim_trace_map', CLAIM_TRACE_MAP_PATH, claim_trace_map, model_cid=model_cid),
        _artifact_entry('source_manifest', SOURCE_MANIFEST_PATH, source_manifest),
        _artifact_entry('source_claim_map', SOURCE_CLAIM_MAP_PATH, source_claim_map),
        _artifact_entry('xrpl_transaction_coverage', XRPL_TRANSACTION_COVERAGE_PATH, xrpl_transaction_coverage),
        _artifact_entry('disproof_vectors', DISPROOF_VECTORS_PATH, disproof_vectors),
    ]

    manifest: dict[str, Any] = {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'scope': {
            'network': 'XRPL Testnet',
            'network_id': 1,
            'public_source_only': True,
            'production_security_result': False,
            'claim_selection': 'all frozen Testnet blocking/high claims in security-model-ir',
        },
        'source': source,
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'cid': model_cid,
            'model_id': model_payload.get('model_id'),
            'schema_version': model_payload.get('schema_version'),
            'claim_count': len(claims),
            'claim_ids': claim_ids,
            'artifact_cid': calculate_artifact_cid(model_payload),
            'frozen_model_required_for_every_claim': True,
        },
        'dependency_artifacts': dependency_artifacts,
        'lane_inventory': lane_inventory,
        'claim_evidence': claim_evidence,
        'policy': {
            'solver_theory_fit_required': True,
            'only_applicable_lanes_are_consumed_for_claim_results': True,
            'unavailable_disagreeing_timeout_or_missing_required_lane_fails_closed': True,
            'required_reviewer_status': 'human_reviewed',
            'raw_sensitive_material_recorded': False,
            'proof_promotion_rule': (
                'A claim may be promoted only when every applicable required lane is accepted, '
                'no applicable lane reports counterevidence, all evidence refs are reviewed, '
                'and the frozen model CID and evidence digest set match this manifest.'
            ),
        },
    }
    manifest['artifact_cid'] = _cid_without(manifest, 'artifact_cid')
    return manifest


def build_xaman_testnet_solver_portfolio_report(
    *,
    manifest: Mapping[str, Any],
    model_payload: Mapping[str, Any],
    model_cid: str,
    assumptions_payload: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    lean_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the reconciled fail-closed solver portfolio report."""

    if manifest.get('model', {}).get('cid') != model_cid:
        raise ValueError('portfolio manifest model CID does not match the frozen Testnet model CID')
    _validate_report_cids(
        model_cid=model_cid,
        smt_report=smt_report,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        lean_report=lean_report,
        coq_decision=coq_decision,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
    )

    assumption_index = {
        assumption['id']: assumption
        for assumption in assumptions_payload.get('assumptions', model_payload.get('assumptions', []))
    }
    lane_inventory = {lane['lane_id']: lane for lane in manifest.get('lane_inventory', [])}
    smt_claims = {claim['claim_id']: claim for claim in smt_report.get('claims', [])}
    apalache_claims = {claim['claim_id']: claim for claim in apalache_report.get('claim_coverage', [])}
    protocol_claims = {claim['claim_id']: claim for claim in protocol_report.get('claim_coverage', [])}
    lean_covered = set(lean_report.get('coverage', {}).get('covered_claim_ids', []))
    lean_rejected = set(lean_report.get('coverage', {}).get('rejected_scope_claim_ids', []))
    fuzz_index = _fuzz_claim_index(fuzz_report)

    claim_results = []
    for claim in model_payload.get('claims', []):
        claim_id = claim['id']
        evidence = _claim_evidence_digest_set(claim)
        lane_results = []
        skipped_lanes = []
        lane_results.append(
            _smt_lane_result(
                claim_id,
                smt_claims.get(claim_id),
                lane_inventory['z3_cvc5_differential'],
            )
        )
        if claim_id in apalache_claims:
            lane_results.append(
                _apalache_lane_result(
                    claim_id,
                    apalache_claims[claim_id],
                    apalache_report,
                    lane_inventory['apalache_state'],
                )
            )
        else:
            skipped_lanes.append(_skipped_lane('apalache_state', 'claim is not a concurrency/state-machine claim'))

        if claim_id in protocol_claims:
            lane_results.append(
                _protocol_lane_result(
                    claim_id,
                    protocol_claims[claim_id],
                    protocol_report,
                    lane_inventory['tamarin_protocol'],
                    lane_id='tamarin_protocol',
                )
            )
            lane_results.append(
                _protocol_lane_result(
                    claim_id,
                    protocol_claims[claim_id],
                    protocol_report,
                    lane_inventory['proverif_protocol'],
                    lane_id='proverif_protocol',
                )
            )
        else:
            skipped_lanes.append(_skipped_lane('tamarin_protocol', 'claim is outside the protocol projection'))
            skipped_lanes.append(_skipped_lane('proverif_protocol', 'claim is outside the protocol projection'))

        if claim_id in lean_covered:
            lane_results.append(
                _lean_lane_result(claim_id, lean_report, lane_inventory['lean_kernel'])
            )
            lane_results.append(
                _coq_lane_result(claim_id, coq_decision, lane_inventory['rocq_kernel'])
            )
        else:
            reason = 'claim is outside the Lean formalized invariant family'
            if claim_id in lean_rejected:
                reason = 'Lean report explicitly rejects this claim scope for kernel proof promotion'
            skipped_lanes.append(_skipped_lane('lean_kernel', reason))
            skipped_lanes.append(_skipped_lane('rocq_kernel', 'Rocq/Coq mirrors the independent-kernel family only'))

        if claim_id in fuzz_index:
            lane_results.append(
                _fuzz_lane_result(
                    claim_id,
                    fuzz_index[claim_id],
                    fuzz_report,
                    fuzz_counterexample_manifest,
                    lane_inventory['fuzz_consumption'],
                )
            )
        else:
            skipped_lanes.append(_skipped_lane('fuzz_consumption', 'no registered fuzz case targets or triggers this claim'))

        final_result, blockers = _reconcile_claim(lane_results, claim, evidence)
        claim_results.append(
            {
                'claim_id': claim_id,
                'claim_version': claim.get('version', claim.get('claim_version', '1.0')),
                'model_cid': model_cid,
                'model_status': claim.get('status'),
                'severity': claim.get('severity'),
                'domain': claim.get('domain'),
                'coverage_tags': list(claim.get('coverage_tags', [])),
                'evidence_digest_set': evidence,
                'blocked_by_assumptions': list(smt_claims.get(claim_id, {}).get('blocked_by_assumptions', [])),
                'owner_actions': _owner_actions_for_claim(smt_claims.get(claim_id), assumption_index),
                'applicable_lane_results': lane_results,
                'skipped_lanes': skipped_lanes,
                'result': final_result,
                'proof_promotion_allowed': final_result == 'PROVED',
                'fail_closed': final_result != 'PROVED',
                'blockers': blockers,
            }
        )

    summary = _portfolio_summary(claim_results)
    report: dict[str, Any] = {
        'schema_version': REPORT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'manifest': {
            'path': PORTFOLIO_MANIFEST_PATH,
            'schema_version': manifest.get('schema_version'),
            'artifact_cid': manifest.get('artifact_cid') or calculate_artifact_cid(manifest),
        },
        'model': deepcopy(dict(manifest['model'])),
        'source': deepcopy(dict(manifest['source'])),
        'portfolio_policy': deepcopy(dict(manifest['policy'])),
        'lane_inventory': deepcopy(list(manifest['lane_inventory'])),
        'claims': claim_results,
        'summary': summary,
        'overall_status': summary['overall_status'],
        'security_decision': summary['security_decision'],
        'testnet_assurance_blocked': summary['fail_closed_claim_count'] > 0,
        'production_release_blocked': True,
    }
    report['artifact_cid'] = _cid_without(report, 'artifact_cid')
    return report


def render_xaman_testnet_solver_portfolio_markdown(
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
) -> str:
    """Render the portfolio report as a concise review document."""

    summary = report['summary']
    lane_counts = summary['lane_result_counts']
    lines = [
        '# Xaman Testnet Solver Portfolio',
        '',
        f'Task: `{TASK_ID}`',
        '',
        f'Model CID: `{report["model"]["cid"]}`',
        '',
        f'Manifest: `{PORTFOLIO_MANIFEST_PATH}`',
        f'Report: `{PORTFOLIO_REPORT_PATH}`',
        '',
        'This portfolio reconciles the public-source XRPL Testnet model across SMT, '
        'state, protocol, kernel, and fuzz-result lanes. It is not a production-security result.',
        '',
        '## Decision',
        '',
        f'- Overall status: `{report["overall_status"]}`',
        f'- Security decision: `{report["security_decision"]}`',
        f'- Claims: `{summary["claim_count"]}`',
        f'- Fail-closed claims: `{summary["fail_closed_claim_count"]}`',
        f'- Proof-promotable claims: `{summary["proved_claim_count"]}`',
        '',
        '## Lanes',
        '',
    ]
    for lane in manifest.get('lane_inventory', []):
        lines.append(
            f'- `{lane["lane_id"]}`: `{lane["status"]}`; report `{lane["artifact_path"]}`; '
            f'command digest `{lane["command_digest"]}`; timeout `{lane["timeout_seconds"]}` seconds; '
            f'reviewer `{lane["reviewer_status"]}`.'
        )
    lines.extend(
        [
            '',
            '## Lane Result Counts',
            '',
        ]
    )
    for result, count in sorted(lane_counts.items()):
        lines.append(f'- `{result}`: `{count}`')
    lines.extend(
        [
            '',
            '## Claim Results',
            '',
        ]
    )
    for claim in report.get('claims', []):
        lane_text = ', '.join(
            f'{lane["lane_id"]}:{lane["result"]}'
            for lane in claim.get('applicable_lane_results', [])
        )
        lines.append(
            f'- `{claim["claim_id"]}` -> `{claim["result"]}`. '
            f'Evidence set `{claim["evidence_digest_set"]["digest_set_cid"]}`. Lanes: {lane_text}.'
        )
    lines.extend(
        [
            '',
            '## Fail-Closed Policy',
            '',
            'Every unavailable, missing, not-run, disagreeing, timeout, unknown, or counterexample lane is recorded '
            'as fail-closed for the applicable claim. Lanes outside a claim theory are recorded as `NOT_APPLICABLE` '
            'and are not consumed as proof evidence.',
            '',
            'The current portfolio records SMT counterexamples for every frozen Testnet claim, unresolved Apalache '
            'assumptions, required Tamarin/ProVerif protocol blockers, a missing required Rocq/Coq kernel artifact, '
            'and fuzz counterexamples consumed as blocking counterevidence.',
            '',
        ]
    )
    return '\n'.join(lines)


def _validate_model_bindings(
    *,
    model_cid: str,
    model_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
    claim_trace_map: Mapping[str, Any],
    proof_worker_lock: Mapping[str, Any],
    cvc5_runner_report: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    lean_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
) -> None:
    if model_payload.get('metadata', {}).get('production_release_blocked') is not True:
        raise ValueError('solver portfolio must bind to the production-blocking Testnet model')
    bound_inputs = {
        'assumptions': assumptions_payload.get('model_cid'),
        'claim_trace_map': claim_trace_map.get('model_cid'),
        'proof_worker_lock': proof_worker_lock.get('model', {}).get('cid'),
        'cvc5_runner_report': cvc5_runner_report.get('model', {}).get('cid'),
        'smt_report': smt_report.get('model', {}).get('cid'),
        'apalache_report': apalache_report.get('model', {}).get('cid'),
        'protocol_report': protocol_report.get('model', {}).get('cid'),
        'lean_report': lean_report.get('model', {}).get('cid'),
        'coq_decision': coq_decision.get('model', {}).get('cid'),
        'fuzz_report': fuzz_report.get('model', {}).get('cid'),
        'fuzz_counterexample_manifest': fuzz_counterexample_manifest.get('model_cid'),
    }
    mismatches = {
        name: value
        for name, value in bound_inputs.items()
        if value != model_cid
    }
    if mismatches:
        raise ValueError(f'portfolio input model CID mismatch: {mismatches}')


def _validate_report_cids(
    *,
    model_cid: str,
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    lean_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
) -> None:
    for name, payload in {
        'smt_report': smt_report,
        'apalache_report': apalache_report,
        'protocol_report': protocol_report,
        'lean_report': lean_report,
        'coq_decision': coq_decision,
        'fuzz_report': fuzz_report,
    }.items():
        if payload.get('model', {}).get('cid') != model_cid:
            raise ValueError(f'{name} model CID does not match the frozen Testnet model CID')
    if fuzz_counterexample_manifest.get('model_cid') != model_cid:
        raise ValueError('fuzz counterexample manifest model CID does not match the frozen Testnet model CID')


def _source_binding(
    model_payload: Mapping[str, Any],
    source_manifest: Mapping[str, Any] | None,
    source_claim_map: Mapping[str, Any] | None,
) -> dict[str, Any]:
    model_source = model_payload.get('metadata', {}).get('source', {})
    source_map = (source_claim_map or {}).get('source', {})
    manifest_source = (source_manifest or {}).get('source', {})
    return {
        'repository': model_source.get('repository')
        or source_map.get('repository')
        or manifest_source.get('repository')
        or 'XRPL-Labs/Xaman-App',
        'commit_sha': model_source.get('commit_sha')
        or source_map.get('commit_sha')
        or manifest_source.get('commit_sha'),
        'manifest_path': SOURCE_MANIFEST_PATH,
        'source_claim_map_path': SOURCE_CLAIM_MAP_PATH,
        'public_source_only': True,
        'source_manifest_artifact_cid': _maybe_artifact_cid(source_manifest),
        'source_claim_map_artifact_cid': _maybe_artifact_cid(source_claim_map),
    }


def _artifact_entry(
    kind: str,
    path: str,
    payload: Mapping[str, Any] | None,
    *,
    model_cid: str | None = None,
) -> dict[str, Any]:
    exists = payload is not None
    entry: dict[str, Any] = {
        'kind': kind,
        'path': path,
        'exists': exists,
        'schema_version': payload.get('schema_version') if payload else None,
        'task_id': payload.get('task_id') if payload else None,
        'artifact_cid': _maybe_artifact_cid(payload),
    }
    if model_cid is not None:
        entry['model_cid'] = model_cid
    elif payload is not None:
        if isinstance(payload.get('model'), Mapping):
            entry['model_cid'] = payload.get('model', {}).get('cid')
        elif isinstance(payload.get('model_cid'), str):
            entry['model_cid'] = payload.get('model_cid')
    return entry


def _lane_inventory(
    *,
    proof_worker_lock: Mapping[str, Any],
    cvc5_runner_report: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    apalache_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    lean_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    repo_root: Path | None,
) -> list[dict[str, Any]]:
    timeout_ms = int(proof_worker_lock.get('smt_contract', {}).get('timeout_ms') or cvc5_runner_report.get('timeout_ms') or 5000)
    first_smt_claim = next(iter(cvc5_runner_report.get('claims', [])), {})
    z3_version = (
        first_smt_claim.get('solver_results', {})
        .get('z3', {})
        .get('solver_version')
    )
    cvc5 = cvc5_runner_report.get('cvc5', {})
    protocol_lanes = protocol_report.get('solver_lanes', {})
    tamarin = protocol_lanes.get('tamarin', {})
    proverif = protocol_lanes.get('proverif', {})
    lean_compile = lean_report.get('lean', {}).get('compile', {})
    coq_check = coq_decision.get('coq', {}).get('check', {})
    fuzz_command = [
        '/home/barberb/miniforge3/bin/python',
        'scripts/ops/security_verification/run_xaman_testnet_fuzzing.py',
    ]
    lanes = [
        {
            'lane_id': 'z3_cvc5_differential',
            'theory': 'SMT-LIB QF_LIA blocking-acceptance satisfiability',
            'required': True,
            'artifact_path': SMT_REPORT_PATH,
            'artifact_cid': _maybe_artifact_cid(smt_report),
            'status': smt_report.get('overall_status'),
            'security_decision': smt_report.get('security_decision'),
            'solvers': [
                {
                    'name': 'z3',
                    'executable': 'python:z3-solver',
                    'executable_sha256': None,
                    'version': z3_version,
                },
                {
                    'name': 'cvc5',
                    'executable': cvc5.get('executable'),
                    'executable_sha256': _file_sha256(cvc5.get('executable'), repo_root=repo_root),
                    'version': cvc5.get('version'),
                },
            ],
            'commands': _smt_commands(cvc5_runner_report, timeout_ms=timeout_ms),
            'timeout_seconds': timeout_ms / 1000,
            'reviewer_status': _reviewer_status_from_claims(cvc5_runner_report.get('claims', [])),
            'fail_closed_result_for_unavailable_or_disagreeing_lane': 'INCOMPLETE',
        },
        {
            'lane_id': 'apalache_state',
            'theory': 'TLA+ finite Testnet payload-resolution state checks',
            'required': True,
            'artifact_path': APALACHE_REPORT_PATH,
            'artifact_cid': _maybe_artifact_cid(apalache_report),
            'status': apalache_report.get('overall_status'),
            'security_decision': apalache_report.get('security_decision'),
            'solvers': [
                {
                    'name': 'apalache',
                    'executable': apalache_report.get('apalache', {}).get('executable'),
                    'executable_sha256': _file_sha256(apalache_report.get('apalache', {}).get('executable'), repo_root=repo_root),
                    'version': apalache_report.get('apalache', {}).get('version'),
                }
            ],
            'commands': [run.get('command') for run in apalache_report.get('apalache', {}).get('runs', [])],
            'timeout_seconds': 120,
            'reviewer_status': _reviewer_status_from_inputs(apalache_report),
            'fail_closed_result_for_unavailable_or_disagreeing_lane': 'REQUIRED_UNAVAILABLE',
        },
        {
            'lane_id': 'tamarin_protocol',
            'theory': 'Tamarin remote-payload protocol lemmas',
            'required': True,
            'artifact_path': PROTOCOL_REPORT_PATH,
            'artifact_cid': _maybe_artifact_cid(protocol_report),
            'status': tamarin.get('status'),
            'security_decision': protocol_report.get('security_decision'),
            'solvers': [
                {
                    'name': 'tamarin-prover',
                    'executable': tamarin.get('executable'),
                    'executable_sha256': _file_sha256(tamarin.get('executable'), repo_root=repo_root),
                    'version': tamarin.get('version'),
                }
            ],
            'commands': [tamarin.get('command')],
            'timeout_seconds': 120,
            'reviewer_status': _reviewer_status_from_protocol(protocol_report),
            'fail_closed_result_for_unavailable_or_disagreeing_lane': 'NOT_RUN',
        },
        {
            'lane_id': 'proverif_protocol',
            'theory': 'ProVerif remote-payload protocol queries',
            'required': True,
            'artifact_path': PROTOCOL_REPORT_PATH,
            'artifact_cid': _maybe_artifact_cid(protocol_report),
            'status': proverif.get('status'),
            'security_decision': protocol_report.get('security_decision'),
            'solvers': [
                {
                    'name': 'proverif',
                    'executable': proverif.get('executable'),
                    'executable_sha256': _file_sha256(proverif.get('executable'), repo_root=repo_root),
                    'version': proverif.get('version'),
                }
            ],
            'commands': [proverif.get('command')],
            'timeout_seconds': 120,
            'reviewer_status': _reviewer_status_from_protocol(protocol_report),
            'fail_closed_result_for_unavailable_or_disagreeing_lane': 'REQUIRED_MISSING_ARTIFACT',
        },
        {
            'lane_id': 'lean_kernel',
            'theory': 'Lean 4 kernel checks for formalized Boolean invariants',
            'required': True,
            'artifact_path': LEAN_REPORT_PATH,
            'artifact_cid': _maybe_artifact_cid(lean_report),
            'status': lean_report.get('overall_status'),
            'security_decision': lean_report.get('security_decision'),
            'solvers': [
                {
                    'name': 'lean',
                    'executable': lean_report.get('lean', {}).get('executable'),
                    'executable_sha256': _file_sha256(lean_report.get('lean', {}).get('executable'), repo_root=repo_root),
                    'version': lean_report.get('lean', {}).get('version'),
                }
            ],
            'commands': [lean_compile.get('command')],
            'timeout_seconds': 90,
            'reviewer_status': _reviewer_status_from_inputs(lean_report),
            'fail_closed_result_for_unavailable_or_disagreeing_lane': 'INCOMPLETE',
        },
        {
            'lane_id': 'rocq_kernel',
            'theory': 'Rocq/Coq independent kernel coverage decision',
            'required': True,
            'artifact_path': COQ_DECISION_PATH,
            'artifact_cid': _maybe_artifact_cid(coq_decision),
            'status': coq_decision.get('overall_status'),
            'security_decision': coq_decision.get('security_decision'),
            'solvers': [
                {
                    'name': 'rocq/coq',
                    'executable': coq_decision.get('coq', {}).get('coqc_executable'),
                    'executable_sha256': _file_sha256(coq_decision.get('coq', {}).get('coqc_executable'), repo_root=repo_root),
                    'version': coq_decision.get('coq', {}).get('coqc_version'),
                }
            ],
            'commands': [coq_check.get('command')],
            'timeout_seconds': 90,
            'reviewer_status': _reviewer_status_from_inputs(coq_decision),
            'fail_closed_result_for_unavailable_or_disagreeing_lane': 'REQUIRED_MISSING_ARTIFACT',
        },
        {
            'lane_id': 'fuzz_consumption',
            'theory': 'bounded deterministic Testnet fuzz-result consumption',
            'required': True,
            'artifact_path': FUZZ_REPORT_PATH,
            'artifact_cid': _maybe_artifact_cid(fuzz_report),
            'status': fuzz_report.get('summary', {}).get('overall_status'),
            'security_decision': fuzz_report.get('summary', {}).get('security_decision'),
            'solvers': [
                {
                    'name': fuzz_report.get('fuzzer', {}).get('engine', 'deterministic-structural-mutator'),
                    'executable': '/home/barberb/miniforge3/bin/python',
                    'executable_sha256': _file_sha256('/home/barberb/miniforge3/bin/python', repo_root=repo_root),
                    'version': 'python-json-structural-oracle',
                }
            ],
            'commands': [fuzz_command],
            'timeout_seconds': 300,
            'reviewer_status': _reviewer_status_from_inputs(fuzz_report),
            'fail_closed_result_for_unavailable_or_disagreeing_lane': 'INCOMPLETE',
        },
    ]
    for lane in lanes:
        lane['commands'] = [command for command in lane['commands'] if command]
        lane['command_digest'] = _command_digest(lane['commands'])
        lane['available'] = all(solver.get('executable') is not None for solver in lane['solvers'])
        lane['executable_versions_recorded'] = all(solver.get('version') is not None for solver in lane['solvers'])
    return lanes


def _claim_manifest_entry(claim: Mapping[str, Any], *, model_cid: str) -> dict[str, Any]:
    evidence = _claim_evidence_digest_set(claim)
    return {
        'claim_id': claim['id'],
        'claim_version': claim.get('version', claim.get('claim_version', '1.0')),
        'model_cid': model_cid,
        'severity': claim.get('severity'),
        'status': claim.get('status'),
        'coverage_tags': list(claim.get('coverage_tags', [])),
        'evidence_digest_set': evidence,
    }


def _claim_evidence_digest_set(claim: Mapping[str, Any]) -> dict[str, Any]:
    refs = []
    for ref in claim.get('evidence_refs', []):
        if not isinstance(ref, Mapping):
            continue
        refs.append(
            {
                'kind': ref.get('kind'),
                'path': ref.get('path'),
                'sha256': ref.get('sha256'),
                'line_start': ref.get('line_start'),
                'line_end': ref.get('line_end'),
                'review_status': ref.get('review_status'),
            }
        )
    refs = sorted(refs, key=lambda item: (str(item.get('path')), str(item.get('line_start')), str(item.get('sha256'))))
    reviewer_statuses = sorted({str(ref.get('review_status')) for ref in refs if ref.get('review_status')})
    payload = {
        'claim_id': claim.get('id'),
        'evidence_refs': refs,
    }
    return {
        'digest_set_cid': calculate_artifact_cid(payload),
        'evidence_ref_count': len(refs),
        'reviewer_statuses': reviewer_statuses,
        'all_human_reviewed': bool(refs) and all(ref.get('review_status') == 'human_reviewed' for ref in refs),
        'refs': refs,
    }


def _smt_lane_result(
    claim_id: str,
    smt_claim: Mapping[str, Any] | None,
    lane: Mapping[str, Any],
) -> dict[str, Any]:
    if smt_claim is None:
        return _required_lane_result(
            lane,
            claim_id,
            result='REQUIRED_MISSING_ARTIFACT',
            reason='claim is missing from the Z3/CVC5 differential report',
        )
    solver_tuple = smt_claim.get('solver_tuple', {})
    if smt_claim.get('result') == 'PROVED':
        result = 'ACCEPTED'
        fail_closed = False
    elif smt_claim.get('result') == 'COUNTEREXAMPLE':
        result = 'COUNTEREXAMPLE'
        fail_closed = True
    else:
        result = 'INCOMPLETE'
        fail_closed = True
    return _lane_result(
        lane,
        claim_id,
        result=result,
        accepted=not fail_closed,
        fail_closed=fail_closed,
        reason=smt_claim.get('worker_classification_reason'),
        details={
            'solver_tuple': solver_tuple,
            'worker_classification': smt_claim.get('worker_classification'),
            'counterexample_path': smt_claim.get('counterexample_path'),
            'smtlib_artifact': smt_claim.get('smtlib_artifact'),
        },
    )


def _apalache_lane_result(
    claim_id: str,
    claim_coverage: Mapping[str, Any],
    report: Mapping[str, Any],
    lane: Mapping[str, Any],
) -> dict[str, Any]:
    summary = report.get('summary', {})
    all_checked = bool(summary.get('all_required_invariants_checked'))
    unresolved = int(summary.get('unresolved_required_assumption_count') or 0)
    run_failures = int(summary.get('run_failure_count') or 0)
    available = bool(report.get('apalache', {}).get('available'))
    if not available:
        result = 'REQUIRED_UNAVAILABLE'
    elif run_failures:
        result = 'FAILED'
    elif unresolved:
        result = 'INCOMPLETE'
    elif all_checked:
        result = 'ACCEPTED'
    else:
        result = 'INCOMPLETE'
    return _lane_result(
        lane,
        claim_id,
        result=result,
        accepted=result == 'ACCEPTED',
        fail_closed=result != 'ACCEPTED',
        reason=report.get('security_decision'),
        details={
            'modeled_by_invariants': list(claim_coverage.get('modeled_by_invariants', [])),
            'unresolved_required_assumptions': deepcopy(list(report.get('unresolved_required_assumptions', []))),
            'checked_invariant_count': summary.get('checked_invariant_count'),
            'run_failure_count': run_failures,
        },
    )


def _protocol_lane_result(
    claim_id: str,
    claim_coverage: Mapping[str, Any],
    report: Mapping[str, Any],
    lane: Mapping[str, Any],
    *,
    lane_id: str,
) -> dict[str, Any]:
    solver_key = 'tamarin' if lane_id == 'tamarin_protocol' else 'proverif'
    solver_lane = report.get('solver_lanes', {}).get(solver_key, {})
    blockers = list(report.get('blockers', []))
    status = str(solver_lane.get('status'))
    available = bool(solver_lane.get('available'))
    if not available:
        result = 'REQUIRED_UNAVAILABLE'
    elif status == 'passed' and not blockers:
        result = 'ACCEPTED'
    elif status == 'not-run':
        result = 'NOT_RUN'
    elif status == 'timeout':
        result = 'TIMEOUT'
    elif status in {'failed', 'unknown'}:
        result = status.upper()
    else:
        result = 'INCOMPLETE'
    if lane_id == 'proverif_protocol' and not report.get('proverif_model', {}).get('exists'):
        result = 'REQUIRED_MISSING_ARTIFACT'
    return _lane_result(
        lane,
        claim_id,
        result=result,
        accepted=result == 'ACCEPTED',
        fail_closed=result != 'ACCEPTED',
        reason=report.get('security_decision'),
        details={
            'protocol_status': claim_coverage.get('protocol_status'),
            'modeled_by_lemmas': list(claim_coverage.get('modeled_by_lemmas', [])),
            'blockers': deepcopy(blockers),
        },
    )


def _lean_lane_result(
    claim_id: str,
    report: Mapping[str, Any],
    lane: Mapping[str, Any],
) -> dict[str, Any]:
    compile_payload = report.get('lean', {}).get('compile', {})
    checked = compile_payload.get('status') == 'passed' and compile_payload.get('returncode') == 0
    result = 'ACCEPTED' if checked else 'INCOMPLETE'
    return _lane_result(
        lane,
        claim_id,
        result=result,
        accepted=checked,
        fail_closed=not checked,
        reason=report.get('security_decision'),
        details={
            'formalized_invariants': list(report.get('kernel', {}).get('formalized_invariants', [])),
            'theorem_count': report.get('summary', {}).get('theorem_count'),
            'formalized_invariant_only': True,
        },
    )


def _coq_lane_result(
    claim_id: str,
    report: Mapping[str, Any],
    lane: Mapping[str, Any],
) -> dict[str, Any]:
    coq = report.get('coq', {})
    check = coq.get('check', {})
    checked = check.get('status') == 'passed' and check.get('returncode') == 0
    if checked:
        result = 'ACCEPTED'
    elif not coq.get('kernel_present'):
        result = 'REQUIRED_MISSING_ARTIFACT'
    elif not coq.get('coqc_present'):
        result = 'REQUIRED_UNAVAILABLE'
    else:
        result = 'INCOMPLETE'
    return _lane_result(
        lane,
        claim_id,
        result=result,
        accepted=checked,
        fail_closed=not checked,
        reason=report.get('security_decision'),
        details={
            'decision': report.get('decision'),
            'coq_required_by_reviewed_threat_model': report.get('coq_required_by_reviewed_threat_model'),
            'kernel_present': coq.get('kernel_present'),
            'coqc_present': coq.get('coqc_present'),
        },
    )


def _fuzz_lane_result(
    claim_id: str,
    cases: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
    counterexample_manifest: Mapping[str, Any],
    lane: Mapping[str, Any],
) -> dict[str, Any]:
    failed = int(report.get('summary', {}).get('failed_case_count') or 0)
    crashes = int(report.get('summary', {}).get('fuzzer_crash_count') or 0)
    counterexample_paths = sorted(
        {
            str(case.get('counterexample_path'))
            for case in cases
            if case.get('counterexample_path')
        }
    )
    if failed or crashes:
        result = 'FAILED'
    elif counterexample_paths:
        result = 'COUNTEREXAMPLE'
    else:
        result = 'ACCEPTED'
    return _lane_result(
        lane,
        claim_id,
        result=result,
        accepted=result == 'ACCEPTED',
        fail_closed=result != 'ACCEPTED',
        reason=report.get('summary', {}).get('security_decision'),
        details={
            'case_count': len(cases),
            'counterexample_paths': counterexample_paths,
            'counterexample_manifest': {
                'path': FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
                'artifact_cid': counterexample_manifest.get('artifact_cid'),
                'counterexample_count': counterexample_manifest.get('counterexample_count'),
            },
        },
    )


def _lane_result(
    lane: Mapping[str, Any],
    claim_id: str,
    *,
    result: str,
    accepted: bool,
    fail_closed: bool,
    reason: str | None,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        'lane_id': lane['lane_id'],
        'claim_id': claim_id,
        'theory': lane['theory'],
        'required': lane['required'],
        'artifact_path': lane['artifact_path'],
        'artifact_cid': lane['artifact_cid'],
        'result': result,
        'accepted': accepted,
        'fail_closed': fail_closed,
        'reason': reason,
        'solvers': deepcopy(list(lane.get('solvers', []))),
        'command_digest': lane.get('command_digest'),
        'commands': deepcopy(list(lane.get('commands', []))),
        'timeout_seconds': lane.get('timeout_seconds'),
        'reviewer_status': lane.get('reviewer_status'),
        'details': deepcopy(dict(details)),
    }


def _required_lane_result(
    lane: Mapping[str, Any],
    claim_id: str,
    *,
    result: str,
    reason: str,
) -> dict[str, Any]:
    return _lane_result(
        lane,
        claim_id,
        result=result,
        accepted=False,
        fail_closed=True,
        reason=reason,
        details={},
    )


def _skipped_lane(lane_id: str, reason: str) -> dict[str, Any]:
    return {
        'lane_id': lane_id,
        'result': 'NOT_APPLICABLE',
        'reason': reason,
        'fail_closed': False,
    }


def _reconcile_claim(
    lane_results: Sequence[Mapping[str, Any]],
    claim: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    blockers = []
    if not evidence.get('all_human_reviewed'):
        blockers.append(
            {
                'code': 'EVIDENCE_NOT_HUMAN_REVIEWED',
                'source': 'claim.evidence_refs',
            }
        )
    if claim.get('status') == 'NOT_MODELED':
        blockers.append(
            {
                'code': 'CLAIM_NOT_MODELED',
                'source': MODEL_PATH,
            }
        )
    for lane in lane_results:
        if lane.get('result') in FAIL_CLOSED_STATUSES or lane.get('fail_closed'):
            blockers.append(
                {
                    'code': f'{lane["lane_id"].upper()}_{lane["result"]}',
                    'source': lane.get('artifact_path'),
                    'reason': lane.get('reason'),
                }
            )
    if blockers:
        if any(lane.get('result') == 'COUNTEREXAMPLE' for lane in lane_results):
            return 'NON_SECURE_COUNTEREVIDENCE', blockers
        return 'FAIL_CLOSED_INCOMPLETE', blockers
    return 'PROVED', blockers


def _portfolio_summary(claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    claim_results = Counter(str(claim.get('result')) for claim in claims)
    lane_results = Counter(
        str(lane.get('result'))
        for claim in claims
        for lane in claim.get('applicable_lane_results', [])
    )
    fail_closed_claim_count = sum(bool(claim.get('fail_closed')) for claim in claims)
    proved_claim_count = sum(claim.get('result') == 'PROVED' for claim in claims)
    if lane_results.get('COUNTEREXAMPLE', 0):
        overall_status = 'non_secure_with_counterevidence'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_SOLVER_PORTFOLIO_COUNTEREVIDENCE'
    elif fail_closed_claim_count:
        overall_status = 'fail_closed_incomplete_required_lanes'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_SOLVER_PORTFOLIO_INCOMPLETE'
    else:
        overall_status = 'proved'
        security_decision = 'TESTNET_SOLVER_PORTFOLIO_PROVED'
    return {
        'claim_count': len(claims),
        'proved_claim_count': proved_claim_count,
        'fail_closed_claim_count': fail_closed_claim_count,
        'claim_result_counts': dict(sorted(claim_results.items())),
        'lane_result_counts': dict(sorted(lane_results.items())),
        'applicable_lane_result_count': sum(len(claim.get('applicable_lane_results', [])) for claim in claims),
        'skipped_lane_count': sum(len(claim.get('skipped_lanes', [])) for claim in claims),
        'overall_status': overall_status,
        'security_decision': security_decision,
    }


def _owner_actions_for_claim(
    smt_claim: Mapping[str, Any] | None,
    assumption_index: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not smt_claim:
        return []
    actions = list(smt_claim.get('owner_actions', []))
    if actions:
        return deepcopy(actions)
    result = []
    for assumption_id in smt_claim.get('blocked_by_assumptions', []):
        assumption = assumption_index.get(assumption_id, {})
        result.append(
            {
                'assumption_id': assumption_id,
                'owner': assumption.get('owner'),
                'status': assumption.get('status'),
                'required_evidence_to_clear': deepcopy(list(assumption.get('required_evidence_to_clear', []))),
            }
        )
    return result


def _fuzz_claim_index(fuzz_report: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for mutation in fuzz_report.get('attack_mutations', []):
        _index_fuzz_case(index, mutation)
    for campaign in fuzz_report.get('campaigns', []):
        for case in campaign.get('cases', []):
            _index_fuzz_case(index, case)
    return dict(index)


def _index_fuzz_case(index: dict[str, list[Mapping[str, Any]]], case: Mapping[str, Any]) -> None:
    claim_ids = set()
    if isinstance(case.get('target_claim_id'), str):
        claim_ids.add(case['target_claim_id'])
    for claim_id in case.get('triggered_claim_ids', []):
        if isinstance(claim_id, str):
            claim_ids.add(claim_id)
    for claim_id in claim_ids:
        index[claim_id].append(case)


def _smt_commands(cvc5_runner_report: Mapping[str, Any], *, timeout_ms: int) -> list[list[str]]:
    cvc5_executable = cvc5_runner_report.get('cvc5', {}).get('executable') or 'cvc5'
    commands = []
    for claim in cvc5_runner_report.get('claims', []):
        smtlib_path = claim.get('smtlib_artifact', {}).get('path')
        if smtlib_path:
            commands.append(['python:z3-solver', f'--timeout-ms={timeout_ms}', smtlib_path])
            commands.append([cvc5_executable, '--lang=smt2', f'--tlimit-per={timeout_ms}', smtlib_path])
    return commands


def _command_digest(commands: Sequence[Any]) -> str:
    return 'sha256:' + hashlib.sha256(
        json.dumps(commands, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    ).hexdigest()


def _file_sha256(path_value: str | None, *, repo_root: Path | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute() and repo_root is not None:
        path = repo_root / path
    try:
        if path.is_file():
            return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return None


def _reviewer_status_from_claims(claims: Sequence[Mapping[str, Any]]) -> str:
    refs = [
        ref
        for claim in claims
        for ref in claim.get('evidence_refs', [])
        if isinstance(ref, Mapping)
    ]
    if refs and all(ref.get('review_status') == 'human_reviewed' for ref in refs):
        return 'human_reviewed'
    if refs:
        return 'mixed_or_unreviewed'
    return 'not_recorded'


def _reviewer_status_from_inputs(report: Mapping[str, Any]) -> str:
    if report.get('inputs', {}).get('assumptions') or report.get('inputs', {}).get('claim_trace_map'):
        return 'human_reviewed'
    return 'not_recorded'


def _reviewer_status_from_protocol(report: Mapping[str, Any]) -> str:
    records = report.get('unsupported_protocol_semantics', [])
    if records and all(record.get('evidence_review_status') == 'human_reviewed' for record in records):
        return 'human_reviewed'
    if records:
        return 'mixed_or_unreviewed'
    return _reviewer_status_from_inputs(report)


def _maybe_artifact_cid(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    for key in ('artifact_cid', 'report_cid', 'lock_cid'):
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


__all__ = [
    'APALACHE_REPORT_PATH',
    'ASSUMPTIONS_PATH',
    'CLAIM_TRACE_MAP_PATH',
    'COQ_DECISION_PATH',
    'CVC5_RUNNER_REPORT_PATH',
    'DISPROOF_VECTORS_PATH',
    'FUZZ_COUNTEREXAMPLE_MANIFEST_PATH',
    'FUZZ_REPORT_PATH',
    'LEAN_REPORT_PATH',
    'MANIFEST_SCHEMA_VERSION',
    'MODEL_CID_PATH',
    'MODEL_PATH',
    'PORTFOLIO_DOC_PATH',
    'PORTFOLIO_MANIFEST_PATH',
    'PORTFOLIO_REPORT_PATH',
    'PROOF_WORKER_LOCK_PATH',
    'PROTOCOL_REPORT_PATH',
    'REPORT_SCHEMA_VERSION',
    'SMT_REPORT_PATH',
    'SOURCE_CLAIM_MAP_PATH',
    'SOURCE_MANIFEST_PATH',
    'TASK_ID',
    'XRPL_TRANSACTION_COVERAGE_PATH',
    'build_xaman_testnet_solver_portfolio_manifest',
    'build_xaman_testnet_solver_portfolio_report',
    'render_xaman_testnet_solver_portfolio_markdown',
]
