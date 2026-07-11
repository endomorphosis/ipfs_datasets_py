"""Bounded public-source/Testnet assurance verdict for Xaman.

This report consumes already-reviewed public-source, Testnet runtime, solver,
and fuzz artifacts. It does not create new proof evidence and it never promotes
public-source/Testnet evidence into a production or vendor-release decision.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-151'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
BUNDLE_SCHEMA_VERSION = 'xaman-public-source-testnet-assurance-bundle/v1'
VERDICT_SCHEMA_VERSION = 'xaman-public-source-testnet-assurance-verdict/v1'

XAMAN_ROOT = 'security_ir_artifacts/corpora/xaman-app'
TESTNET_ROOT = f'{XAMAN_ROOT}/testnet'

MODEL_PATH = f'{TESTNET_ROOT}/security-model-ir.json'
MODEL_CID_PATH = f'{TESTNET_ROOT}/security-model-ir.cid'
PUBLIC_SOURCE_ASSESSMENT_PATH = f'{XAMAN_ROOT}/public-source-assessment.json'
PUBLIC_BUILD_REPRODUCTION_PATH = f'{TESTNET_ROOT}/public-build-reproduction.json'
PUBLIC_BUILD_ENVIRONMENT_PATH = f'{TESTNET_ROOT}/public-build-environment.json'
SOLVER_PORTFOLIO_REPORT_PATH = f'{TESTNET_ROOT}/solver-portfolio-report.json'
FUZZ_CAMPAIGN_MANIFEST_PATH = f'{TESTNET_ROOT}/fuzz/campaign-manifest.json'
FUZZ_COUNTEREXAMPLE_MANIFEST_PATH = f'{TESTNET_ROOT}/fuzz/counterexamples/manifest.json'
FUZZ_REPORT_PATH = f'{TESTNET_ROOT}/fuzz/fuzz-report.json'
RUNTIME_CONFORMANCE_REPORT_PATH = f'{TESTNET_ROOT}/runtime-conformance-report.json'
RUNTIME_CONFORMANCE_TRACE_MAP_PATH = f'{TESTNET_ROOT}/runtime-conformance-trace-map.json'

PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH = (
    f'{TESTNET_ROOT}/public-source-testnet-assurance-bundle.json'
)
PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH = (
    f'{TESTNET_ROOT}/public-source-testnet-assurance-verdict.json'
)
PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH = (
    'docs/security_verification/xaman_public_source_testnet_assurance_verdict.md'
)

ALLOWED_VERDICTS = (
    'TESTNET_SCOPE_ASSURED',
    'DISPROVED',
    'UNKNOWN',
    'NOT_MODELED',
    'BLOCKED',
)

NON_PRODUCTION_STATEMENT = (
    'This is not a production or vendor-release security decision. It is bounded '
    'to reviewed public-source and XRPL Testnet verifier evidence and cannot '
    'approve, certify, reject, or reproduce the production Xaman vendor release.'
)


class PublicSourceTestnetAssuranceError(ValueError):
    """Raised when the bounded verdict bundle violates its fail-closed policy."""


def _cid_without(payload: Mapping[str, Any], *keys: str) -> str:
    skipped = set(keys)
    return calculate_artifact_cid(
        {key: value for key, value in payload.items() if key not in skipped}
    )


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    value = payload.get('artifact_cid') or payload.get('report_cid')
    if isinstance(value, str) and value:
        return value
    return calculate_artifact_cid(payload)


def _sha256_file(repo_root: Path | None, rel_path: str) -> str | None:
    if repo_root is None:
        return None
    path = repo_root / rel_path
    if not path.is_file():
        return None
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_entry(
    kind: str,
    path: str,
    payload: Mapping[str, Any],
    *,
    repo_root: Path | None,
) -> dict[str, Any]:
    entry = {
        'kind': kind,
        'path': path,
        'present': True,
        'schema_version': payload.get('schema_version'),
        'task_id': payload.get('task_id'),
        'artifact_cid': _artifact_cid(payload),
        'sha256': _sha256_file(repo_root, path),
    }
    for key in (
        'overall_status',
        'security_decision',
        'public_source_result',
        'production_release_blocked',
        'testnet_assurance_blocked',
    ):
        if key in payload:
            entry[key] = payload[key]
    return entry


def _runtime_category_index(
    runtime_conformance_report: Mapping[str, Any],
) -> dict[str, list[Mapping[str, Any]]]:
    by_claim: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for category in runtime_conformance_report.get('runtime_categories', []):
        if not isinstance(category, Mapping):
            continue
        for claim_id in category.get('claim_ids', []):
            if isinstance(claim_id, str):
                by_claim[claim_id].append(category)
    return dict(by_claim)


def _fuzz_counterexample_counts(
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for mutation in fuzz_report.get('attack_mutations', []):
        if not isinstance(mutation, Mapping):
            continue
        ids = []
        target = mutation.get('target_claim_id')
        if isinstance(target, str):
            ids.append(target)
        ids.extend(
            claim_id
            for claim_id in mutation.get('triggered_claim_ids', [])
            if isinstance(claim_id, str)
        )
        for claim_id in set(ids):
            counts[claim_id] += 1

    # The manifest is the authority for minimized counterexample quantity. If a
    # future report omits attack_mutations, preserve a fail-closed aggregate.
    if not counts and fuzz_counterexample_manifest.get('counterexample_count'):
        counts['__unattributed__'] = int(fuzz_counterexample_manifest['counterexample_count'])
    return dict(sorted(counts.items()))


def _source_evidence_current_reviewed(claim: Mapping[str, Any]) -> bool:
    refs = claim.get('evidence_refs', [])
    if not refs:
        return False
    for ref in refs:
        if not isinstance(ref, Mapping):
            return False
        if ref.get('review_status') != 'human_reviewed':
            return False
        if not isinstance(ref.get('sha256'), str) or not ref['sha256']:
            return False
        if not isinstance(ref.get('path'), str) or not ref['path']:
            return False
    return True


def _runtime_evidence_current_reviewed(categories: Sequence[Mapping[str, Any]]) -> bool:
    if not categories:
        return False
    for category in categories:
        if category.get('assurance_block') is True:
            return False
        if category.get('model_cid_bound') is not True:
            return False
        if category.get('raw_material_retained') is not False:
            return False
        if category.get('conformance_status') != 'observed':
            return False
    return True


def _solver_evidence_accepted(claim_result: Mapping[str, Any] | None) -> bool:
    if not claim_result:
        return False
    if claim_result.get('proof_promotion_allowed') is not True:
        return False
    if claim_result.get('result') not in {'PROVED', 'ACCEPTED'}:
        return False
    for lane in claim_result.get('applicable_lane_results', []):
        if not isinstance(lane, Mapping):
            return False
        if lane.get('required') is True and lane.get('accepted') is not True:
            return False
        if lane.get('required') is True and lane.get('reviewer_status') != 'human_reviewed':
            return False
        if lane.get('required') is True and not lane.get('command_digest'):
            return False
    return True


def _solver_counterevidence(claim_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not claim_result:
        return [{'code': 'SOLVER_CLAIM_RESULT_MISSING', 'lane_id': None}]
    blockers = []
    for lane in claim_result.get('applicable_lane_results', []):
        if not isinstance(lane, Mapping):
            continue
        result = lane.get('result')
        if result in {
            'COUNTEREXAMPLE',
            'DISAGREE',
            'FAILED',
            'INCOMPLETE',
            'NOT_RUN',
            'REQUIRED_MISSING_ARTIFACT',
            'REQUIRED_UNAVAILABLE',
            'TIMEOUT',
            'UNKNOWN',
        }:
            blockers.append(
                {
                    'code': f'{lane.get("lane_id", "solver").upper()}_{result}',
                    'lane_id': lane.get('lane_id'),
                    'result': result,
                    'reason': lane.get('reason'),
                    'artifact_path': lane.get('artifact_path'),
                    'fail_closed': lane.get('fail_closed'),
                }
            )
    return blockers


def _claim_assurance_rows(
    *,
    model_payload: Mapping[str, Any],
    solver_portfolio_report: Mapping[str, Any],
    runtime_conformance_report: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
    model_cid: str,
) -> list[dict[str, Any]]:
    solver_claims = {
        claim['claim_id']: claim
        for claim in solver_portfolio_report.get('claims', [])
        if isinstance(claim, Mapping) and isinstance(claim.get('claim_id'), str)
    }
    runtime_by_claim = _runtime_category_index(runtime_conformance_report)
    fuzz_counts = _fuzz_counterexample_counts(fuzz_report, fuzz_counterexample_manifest)

    rows = []
    for claim in model_payload.get('claims', []):
        if not isinstance(claim, Mapping) or not isinstance(claim.get('id'), str):
            continue
        claim_id = claim['id']
        solver_claim = solver_claims.get(claim_id)
        runtime_categories = runtime_by_claim.get(claim_id, [])
        source_ok = _source_evidence_current_reviewed(claim)
        runtime_ok = _runtime_evidence_current_reviewed(runtime_categories)
        solver_ok = _solver_evidence_accepted(solver_claim)
        fuzz_count = fuzz_counts.get(claim_id, 0)
        active_not_modeled = claim.get('status') in {
            'NOT_MODELED',
            'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY',
        }
        assurance_ready = (
            source_ok
            and runtime_ok
            and solver_ok
            and fuzz_count == 0
            and not active_not_modeled
        )
        rows.append(
            {
                'claim_id': claim_id,
                'severity': claim.get('severity'),
                'domain': claim.get('domain'),
                'model_cid': model_cid,
                'model_status': claim.get('status'),
                'required_assumptions': deepcopy(claim.get('required_assumptions', [])),
                'source_evidence': {
                    'current_reviewed': source_ok,
                    'review_statuses': sorted(
                        {
                            str(ref.get('review_status'))
                            for ref in claim.get('evidence_refs', [])
                            if isinstance(ref, Mapping)
                        }
                    ),
                    'evidence_ref_count': len(claim.get('evidence_refs', [])),
                },
                'runtime_evidence': {
                    'current_reviewed': runtime_ok,
                    'category_ids': [category.get('category_id') for category in runtime_categories],
                    'conformance_statuses': sorted(
                        {str(category.get('conformance_status')) for category in runtime_categories}
                    ),
                    'assurance_block_count': sum(
                        1 for category in runtime_categories if category.get('assurance_block') is True
                    ),
                },
                'solver_evidence': {
                    'required_results_accepted': solver_ok,
                    'portfolio_result': solver_claim.get('result') if solver_claim else None,
                    'proof_promotion_allowed': (
                        solver_claim.get('proof_promotion_allowed') if solver_claim else False
                    ),
                    'applicable_lane_count': (
                        len(solver_claim.get('applicable_lane_results', []))
                        if solver_claim
                        else 0
                    ),
                    'counterevidence': _solver_counterevidence(solver_claim),
                },
                'fuzz_evidence': {
                    'counterexample_count': fuzz_count,
                    'counterexample_manifest_path': FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
                    'minimized_counterexamples_required': True,
                },
                'assurance_ready_for_testnet_scope_assured': assurance_ready,
            }
        )
    return rows


def _blockers(
    *,
    public_source_assessment: Mapping[str, Any],
    public_build_reproduction: Mapping[str, Any],
    solver_portfolio_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
    runtime_conformance_report: Mapping[str, Any],
    claim_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    blockers = []
    solver_counterevidence_count = sum(
        1
        for claim in solver_portfolio_report.get('claims', [])
        if isinstance(claim, Mapping) and claim.get('result') == 'NON_SECURE_COUNTEREVIDENCE'
    )
    if solver_counterevidence_count:
        blockers.append(
            {
                'code': 'SOLVER_PORTFOLIO_COUNTEREVIDENCE',
                'severity': 'disproof',
                'source': SOLVER_PORTFOLIO_REPORT_PATH,
                'count': solver_counterevidence_count,
            }
        )
    fuzz_count = int(fuzz_counterexample_manifest.get('counterexample_count') or 0)
    if fuzz_count:
        blockers.append(
            {
                'code': 'ADVERSARIAL_FUZZ_COUNTEREXAMPLES',
                'severity': 'disproof',
                'source': FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
                'count': fuzz_count,
            }
        )
    known_public_counterexamples = int(
        public_source_assessment.get('summary', {}).get('known_counterexample_count') or 0
    )
    if known_public_counterexamples:
        blockers.append(
            {
                'code': 'PUBLIC_SOURCE_KNOWN_COUNTEREXAMPLES',
                'severity': 'disproof',
                'source': PUBLIC_SOURCE_ASSESSMENT_PATH,
                'count': known_public_counterexamples,
            }
        )
    runtime_blocks = int(runtime_conformance_report.get('summary', {}).get('assurance_block_count') or 0)
    if runtime_blocks:
        blockers.append(
            {
                'code': 'RUNTIME_CONFORMANCE_ASSURANCE_BLOCKS',
                'severity': 'blocking',
                'source': RUNTIME_CONFORMANCE_REPORT_PATH,
                'count': runtime_blocks,
            }
        )
    failed_claims = [
        row['claim_id']
        for row in claim_rows
        if row.get('assurance_ready_for_testnet_scope_assured') is not True
    ]
    if failed_claims:
        blockers.append(
            {
                'code': 'REQUIRED_CLAIMS_NOT_TESTNET_SCOPE_ASSURED',
                'severity': 'blocking',
                'source': MODEL_PATH,
                'count': len(failed_claims),
                'claim_ids': failed_claims,
            }
        )
    not_modeled_claims = [
        row['claim_id']
        for row in claim_rows
        if row.get('model_status') in {'NOT_MODELED', 'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY'}
    ]
    if not_modeled_claims:
        blockers.append(
            {
                'code': 'ACTIVE_NOT_MODELED_BOUNDARIES',
                'severity': 'not_modeled',
                'source': MODEL_PATH,
                'count': len(not_modeled_claims),
                'claim_ids': not_modeled_claims,
            }
        )
    if public_build_reproduction.get('scope', {}).get('vendor_release_equivalent') is not True:
        blockers.append(
            {
                'code': 'PUBLIC_BUILD_NOT_VENDOR_RELEASE_EQUIVALENT',
                'severity': 'scope',
                'source': PUBLIC_BUILD_REPRODUCTION_PATH,
            }
        )
    if public_source_assessment.get('production_release_approval') is not True:
        blockers.append(
            {
                'code': 'PUBLIC_SOURCE_NOT_PRODUCTION_RELEASE_APPROVAL',
                'severity': 'scope',
                'source': PUBLIC_SOURCE_ASSESSMENT_PATH,
            }
        )
    return blockers


def _assurance_gate(
    claim_rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    all_source = all(row['source_evidence']['current_reviewed'] is True for row in claim_rows)
    all_runtime = all(row['runtime_evidence']['current_reviewed'] is True for row in claim_rows)
    all_solver = all(row['solver_evidence']['required_results_accepted'] is True for row in claim_rows)
    no_fuzz_counterexamples = all(
        row['fuzz_evidence']['counterexample_count'] == 0 for row in claim_rows
    )
    no_not_modeled = all(
        row['model_status'] not in {'NOT_MODELED', 'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY'}
        for row in claim_rows
    )
    no_disproof = not any(blocker.get('severity') == 'disproof' for blocker in blockers)
    return {
        'testnet_scope_assured_allowed': (
            all_source
            and all_runtime
            and all_solver
            and no_fuzz_counterexamples
            and no_not_modeled
            and no_disproof
        ),
        'all_required_claims_have_current_reviewed_source_evidence': all_source,
        'all_required_claims_have_current_reviewed_runtime_evidence': all_runtime,
        'all_required_claims_have_required_solver_results': all_solver,
        'no_fuzz_counterexamples_for_required_claims': no_fuzz_counterexamples,
        'no_active_not_modeled_boundaries': no_not_modeled,
        'no_disproof_counterevidence': no_disproof,
        'production_or_vendor_release_security_decision': False,
        'non_production_statement': NON_PRODUCTION_STATEMENT,
    }


def _derive_verdict(bundle: Mapping[str, Any]) -> str:
    gate = bundle['testnet_scope_assured_gate']
    if gate.get('testnet_scope_assured_allowed') is True:
        return 'TESTNET_SCOPE_ASSURED'
    blocker_severities = {blocker.get('severity') for blocker in bundle.get('blockers', [])}
    if 'disproof' in blocker_severities:
        return 'DISPROVED'
    if 'not_modeled' in blocker_severities:
        return 'NOT_MODELED'
    if 'blocking' in blocker_severities:
        return 'BLOCKED'
    return 'UNKNOWN'


def build_public_source_testnet_assurance_bundle(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    public_source_assessment: Mapping[str, Any],
    public_build_reproduction: Mapping[str, Any],
    public_build_environment: Mapping[str, Any],
    solver_portfolio_report: Mapping[str, Any],
    fuzz_campaign_manifest: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    runtime_conformance_report: Mapping[str, Any],
    runtime_conformance_trace_map: Mapping[str, Any],
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Build the deterministic bounded public-source/Testnet assurance bundle."""

    claim_rows = _claim_assurance_rows(
        model_payload=model_payload,
        solver_portfolio_report=solver_portfolio_report,
        runtime_conformance_report=runtime_conformance_report,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
        model_cid=model_cid,
    )
    blockers = _blockers(
        public_source_assessment=public_source_assessment,
        public_build_reproduction=public_build_reproduction,
        solver_portfolio_report=solver_portfolio_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
        runtime_conformance_report=runtime_conformance_report,
        claim_rows=claim_rows,
    )
    gate = _assurance_gate(claim_rows, blockers)
    claim_status_counts = Counter(str(row['model_status']) for row in claim_rows)
    claim_gate_counts = Counter(
        'ready' if row['assurance_ready_for_testnet_scope_assured'] else 'blocked'
        for row in claim_rows
    )
    bundle = {
        'schema_version': BUNDLE_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'scope': {
            'network': 'XRPL Testnet',
            'network_id': 1,
            'public_source_only': True,
            'verifier_build_only': True,
            'production_security_result': False,
            'vendor_release_security_decision': False,
            'vendor_release_equivalence_claimed': False,
            'statement': NON_PRODUCTION_STATEMENT,
        },
        'allowed_verdicts': list(ALLOWED_VERDICTS),
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'cid': model_cid,
            'schema_version': model_payload.get('schema_version'),
            'model_id': model_payload.get('model_id'),
            'required_claim_count': len(claim_rows),
        },
        'evidence_artifacts': [
            _artifact_entry(
                'public_source_assessment',
                PUBLIC_SOURCE_ASSESSMENT_PATH,
                public_source_assessment,
                repo_root=repo_root,
            ),
            _artifact_entry(
                'public_testnet_build_reproduction',
                PUBLIC_BUILD_REPRODUCTION_PATH,
                public_build_reproduction,
                repo_root=repo_root,
            ),
            _artifact_entry(
                'public_testnet_build_environment',
                PUBLIC_BUILD_ENVIRONMENT_PATH,
                public_build_environment,
                repo_root=repo_root,
            ),
            _artifact_entry(
                'testnet_solver_portfolio',
                SOLVER_PORTFOLIO_REPORT_PATH,
                solver_portfolio_report,
                repo_root=repo_root,
            ),
            _artifact_entry(
                'adversarial_fuzz_campaign',
                FUZZ_CAMPAIGN_MANIFEST_PATH,
                fuzz_campaign_manifest,
                repo_root=repo_root,
            ),
            _artifact_entry(
                'adversarial_fuzz_counterexamples',
                FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
                fuzz_counterexample_manifest,
                repo_root=repo_root,
            ),
            _artifact_entry('bounded_fuzz_report', FUZZ_REPORT_PATH, fuzz_report, repo_root=repo_root),
            _artifact_entry(
                'runtime_conformance_report',
                RUNTIME_CONFORMANCE_REPORT_PATH,
                runtime_conformance_report,
                repo_root=repo_root,
            ),
            _artifact_entry(
                'runtime_conformance_trace_map',
                RUNTIME_CONFORMANCE_TRACE_MAP_PATH,
                runtime_conformance_trace_map,
                repo_root=repo_root,
            ),
        ],
        'dependency_task_ids': ['PORTAL-CXTP-143', 'PORTAL-CXTP-147', 'PORTAL-CXTP-148', 'PORTAL-CXTP-150'],
        'required_claims': claim_rows,
        'claim_summary': {
            'required_claim_count': len(claim_rows),
            'model_status_counts': dict(sorted(claim_status_counts.items())),
            'claim_gate_counts': dict(sorted(claim_gate_counts.items())),
            'source_reviewed_claim_count': sum(
                1 for row in claim_rows if row['source_evidence']['current_reviewed']
            ),
            'runtime_reviewed_claim_count': sum(
                1 for row in claim_rows if row['runtime_evidence']['current_reviewed']
            ),
            'solver_accepted_claim_count': sum(
                1 for row in claim_rows if row['solver_evidence']['required_results_accepted']
            ),
            'fuzz_counterexample_count': int(
                fuzz_counterexample_manifest.get('counterexample_count') or 0
            ),
        },
        'source_runtime_solver_summary': {
            'public_source_security_decision': public_source_assessment.get('security_decision'),
            'public_source_production_release_approval': public_source_assessment.get(
                'production_release_approval'
            ),
            'public_build_security_decision': public_build_reproduction.get('security_decision'),
            'vendor_release_equivalent': public_build_reproduction.get('scope', {}).get(
                'vendor_release_equivalent'
            ),
            'solver_portfolio_security_decision': solver_portfolio_report.get('security_decision'),
            'solver_portfolio_overall_status': solver_portfolio_report.get('overall_status'),
            'runtime_conformance_security_decision': runtime_conformance_report.get(
                'security_decision'
            ),
            'runtime_conformance_overall_status': runtime_conformance_report.get(
                'overall_status'
            ),
            'fuzz_counterexample_count': int(
                fuzz_counterexample_manifest.get('counterexample_count') or 0
            ),
        },
        'testnet_scope_assured_gate': gate,
        'blockers': blockers,
    }
    bundle['artifact_cid'] = _cid_without(bundle, 'artifact_cid')
    validate_public_source_testnet_assurance_bundle(bundle)
    return bundle


def build_public_source_testnet_assurance_verdict(
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the bounded verdict JSON from a generated bundle."""

    validate_public_source_testnet_assurance_bundle(bundle)
    verdict = _derive_verdict(bundle)
    payload = {
        'schema_version': VERDICT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'verdict': verdict,
        'allowed_verdicts': list(ALLOWED_VERDICTS),
        'bundle': {
            'path': PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH,
            'artifact_cid': bundle['artifact_cid'],
            'schema_version': bundle['schema_version'],
        },
        'model': deepcopy(bundle['model']),
        'not_a_production_or_vendor_release_security_decision': True,
        'non_production_statement': NON_PRODUCTION_STATEMENT,
        'testnet_scope_assured_gate': deepcopy(bundle['testnet_scope_assured_gate']),
        'rationale': {
            'primary_reason': (
                'Bounded TESTNET_SCOPE_ASSURED is disproved by current fail-closed '
                'solver/fuzz counterevidence and remains additionally blocked by '
                'runtime, not-modeled, public-source, and vendor-release boundaries.'
                if verdict == 'DISPROVED'
                else 'The bounded public-source/Testnet evidence did not satisfy every assurance gate.'
            ),
            'blocker_codes': [blocker.get('code') for blocker in bundle.get('blockers', [])],
            'disproof_blocker_count': sum(
                1 for blocker in bundle.get('blockers', []) if blocker.get('severity') == 'disproof'
            ),
            'blocking_claim_count': bundle.get('claim_summary', {}).get(
                'claim_gate_counts', {}
            ).get('blocked', 0),
        },
        'required_evidence_or_owner_action_to_advance': _owner_actions(bundle),
        'next_decision_rule': (
            'TESTNET_SCOPE_ASSURED is permitted only after every required claim has '
            'current human-reviewed source evidence, current reviewed runtime evidence, '
            'all applicable required solver results accepted with recorded versions, '
            'command digests, timeouts, and reviewer status, no fail-closed solver or '
            'fuzz counterevidence, and the non-production/vendor-release boundary is '
            'preserved.'
        ),
    }
    payload['artifact_cid'] = _cid_without(payload, 'artifact_cid')
    validate_public_source_testnet_assurance_verdict(payload, bundle)
    return payload


def _owner_actions(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for blocker in bundle.get('blockers', []):
        code = blocker.get('code')
        if code == 'SOLVER_PORTFOLIO_COUNTEREVIDENCE':
            actions.append(
                {
                    'owner': 'formal-methods',
                    'source': SOLVER_PORTFOLIO_REPORT_PATH,
                    'required_action': (
                        'Resolve fail-closed Z3/CVC5, Tamarin/ProVerif, Rocq/Coq, and '
                        'fuzz-consumption counterevidence for every required Testnet claim.'
                    ),
                }
            )
        elif code == 'ADVERSARIAL_FUZZ_COUNTEREXAMPLES':
            actions.append(
                {
                    'owner': 'assurance-fuzzing',
                    'source': FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
                    'required_action': (
                        'Either fix the model/evidence so minimized counterexamples no '
                        'longer trigger required claims or retain DISPROVED.'
                    ),
                }
            )
        elif code == 'RUNTIME_CONFORMANCE_ASSURANCE_BLOCKS':
            actions.append(
                {
                    'owner': 'runtime-verification',
                    'source': RUNTIME_CONFORMANCE_REPORT_PATH,
                    'required_action': (
                        'Provide reviewed, redacted Testnet lifecycle evidence for every '
                        'required runtime path, including cancellation, expiry, replay, '
                        'cryptographic-signing boundary, submit result, and ledger finality.'
                    ),
                }
            )
        elif code == 'ACTIVE_NOT_MODELED_BOUNDARIES':
            actions.append(
                {
                    'owner': 'modeling-review',
                    'source': MODEL_PATH,
                    'required_action': (
                        'Replace active NOT_MODELED boundaries with reviewed modeled claims '
                        'or keep NOT_MODELED/BLOCKED rather than TESTNET_SCOPE_ASSURED.'
                    ),
                }
            )
        elif code == 'PUBLIC_BUILD_NOT_VENDOR_RELEASE_EQUIVALENT':
            actions.append(
                {
                    'owner': 'mobile-build-security',
                    'source': PUBLIC_BUILD_REPRODUCTION_PATH,
                    'required_action': (
                        'Keep public-source Testnet verifier evidence separated from vendor '
                        'release equivalence unless vendor-authorized release provenance is supplied.'
                    ),
                }
            )
        elif code == 'PUBLIC_SOURCE_NOT_PRODUCTION_RELEASE_APPROVAL':
            actions.append(
                {
                    'owner': 'release-security',
                    'source': PUBLIC_SOURCE_ASSESSMENT_PATH,
                    'required_action': (
                        'Do not use this public-source/Testnet verdict as production release approval.'
                    ),
                }
            )
    return actions


def validate_public_source_testnet_assurance_bundle(bundle: Mapping[str, Any]) -> None:
    """Validate the fail-closed bundle contract."""

    if tuple(bundle.get('allowed_verdicts', [])) != ALLOWED_VERDICTS:
        raise PublicSourceTestnetAssuranceError('allowed verdict vocabulary mismatch')
    if bundle.get('scope', {}).get('production_security_result') is not False:
        raise PublicSourceTestnetAssuranceError('bundle cannot be a production security result')
    if bundle.get('scope', {}).get('vendor_release_security_decision') is not False:
        raise PublicSourceTestnetAssuranceError('bundle cannot be a vendor-release decision')
    if NON_PRODUCTION_STATEMENT not in bundle.get('scope', {}).get('statement', ''):
        raise PublicSourceTestnetAssuranceError('non-production statement missing')
    gate = bundle.get('testnet_scope_assured_gate', {})
    if gate.get('testnet_scope_assured_allowed') is True:
        required_true = [
            'all_required_claims_have_current_reviewed_source_evidence',
            'all_required_claims_have_current_reviewed_runtime_evidence',
            'all_required_claims_have_required_solver_results',
            'no_fuzz_counterexamples_for_required_claims',
            'no_active_not_modeled_boundaries',
            'no_disproof_counterevidence',
        ]
        for key in required_true:
            if gate.get(key) is not True:
                raise PublicSourceTestnetAssuranceError(
                    f'TESTNET_SCOPE_ASSURED gate set without {key}'
                )
        for row in bundle.get('required_claims', []):
            if row.get('assurance_ready_for_testnet_scope_assured') is not True:
                raise PublicSourceTestnetAssuranceError(
                    'TESTNET_SCOPE_ASSURED gate set with a non-ready required claim'
                )


def validate_public_source_testnet_assurance_verdict(
    verdict: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> None:
    """Validate the verdict vocabulary and TESTNET_SCOPE_ASSURED guard."""

    value = verdict.get('verdict')
    if value not in ALLOWED_VERDICTS:
        raise PublicSourceTestnetAssuranceError(f'unsupported verdict: {value}')
    if verdict.get('not_a_production_or_vendor_release_security_decision') is not True:
        raise PublicSourceTestnetAssuranceError('verdict lacks non-production boundary')
    if NON_PRODUCTION_STATEMENT not in verdict.get('non_production_statement', ''):
        raise PublicSourceTestnetAssuranceError('non-production statement missing')
    if value == 'TESTNET_SCOPE_ASSURED':
        validate_public_source_testnet_assurance_bundle(bundle)
        if bundle.get('testnet_scope_assured_gate', {}).get('testnet_scope_assured_allowed') is not True:
            raise PublicSourceTestnetAssuranceError(
                'TESTNET_SCOPE_ASSURED requires every source/runtime/solver gate'
            )


def render_public_source_testnet_assurance_markdown(
    bundle: Mapping[str, Any],
    verdict: Mapping[str, Any],
) -> str:
    """Render the human-readable bounded verdict."""

    summary = bundle['source_runtime_solver_summary']
    gate = bundle['testnet_scope_assured_gate']
    lines = [
        '# Xaman Public-Source/Testnet Assurance Verdict',
        '',
        f'Task: `{TASK_ID}`',
        '',
        f'Verdict: `{verdict["verdict"]}`',
        '',
        f'**{NON_PRODUCTION_STATEMENT}**',
        '',
        '## Bound Artifacts',
        '',
        f'- Bundle: `{PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH}`',
        f'- Bundle CID: `{bundle["artifact_cid"]}`',
        f'- Verdict: `{PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH}`',
        f'- Verdict CID: `{verdict["artifact_cid"]}`',
        f'- Model CID: `{bundle["model"]["cid"]}`',
        '',
        '## Basis',
        '',
        f'- Public source: `{summary["public_source_security_decision"]}`; production release approval is `{summary["public_source_production_release_approval"]}`.',
        f'- Public Testnet build: `{summary["public_build_security_decision"]}`; vendor-release equivalent is `{summary["vendor_release_equivalent"]}`.',
        f'- Solver portfolio: `{summary["solver_portfolio_security_decision"]}` with status `{summary["solver_portfolio_overall_status"]}`.',
        f'- Runtime conformance: `{summary["runtime_conformance_security_decision"]}` with status `{summary["runtime_conformance_overall_status"]}`.',
        f'- Adversarial fuzzing: `{summary["fuzz_counterexample_count"]}` minimized counterexamples are bound.',
        '',
        '## TESTNET_SCOPE_ASSURED Gate',
        '',
    ]
    for key in [
        'all_required_claims_have_current_reviewed_source_evidence',
        'all_required_claims_have_current_reviewed_runtime_evidence',
        'all_required_claims_have_required_solver_results',
        'no_fuzz_counterexamples_for_required_claims',
        'no_active_not_modeled_boundaries',
        'no_disproof_counterevidence',
        'testnet_scope_assured_allowed',
    ]:
        lines.append(f'- `{key}`: `{gate[key]}`')
    lines.extend(
        [
            '',
            '## Blockers',
            '',
        ]
    )
    for blocker in bundle.get('blockers', []):
        count = blocker.get('count')
        count_text = f' count `{count}`' if count is not None else ''
        lines.append(
            f'- `{blocker["code"]}` severity `{blocker["severity"]}` from `{blocker["source"]}`{count_text}.'
        )
    lines.extend(
        [
            '',
            '## Required Evidence Or Owner Action',
            '',
        ]
    )
    for action in verdict.get('required_evidence_or_owner_action_to_advance', []):
        lines.append(
            f'- `{action["owner"]}`: {action["required_action"]} Source: `{action["source"]}`.'
        )
    lines.extend(
        [
            '',
            '## Decision Rule',
            '',
            verdict['next_decision_rule'],
            '',
            'Allowed verdict values remain exactly `TESTNET_SCOPE_ASSURED`, `DISPROVED`, '
            '`UNKNOWN`, `NOT_MODELED`, or `BLOCKED`.',
            '',
        ]
    )
    return '\n'.join(lines)


__all__ = [
    'ALLOWED_VERDICTS',
    'BUNDLE_SCHEMA_VERSION',
    'FUZZ_CAMPAIGN_MANIFEST_PATH',
    'FUZZ_COUNTEREXAMPLE_MANIFEST_PATH',
    'FUZZ_REPORT_PATH',
    'MODEL_CID_PATH',
    'MODEL_PATH',
    'NON_PRODUCTION_STATEMENT',
    'PUBLIC_BUILD_ENVIRONMENT_PATH',
    'PUBLIC_BUILD_REPRODUCTION_PATH',
    'PUBLIC_SOURCE_ASSESSMENT_PATH',
    'PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH',
    'PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH',
    'PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH',
    'PublicSourceTestnetAssuranceError',
    'RUNTIME_CONFORMANCE_REPORT_PATH',
    'RUNTIME_CONFORMANCE_TRACE_MAP_PATH',
    'SOLVER_PORTFOLIO_REPORT_PATH',
    'TASK_ID',
    'VERDICT_SCHEMA_VERSION',
    'build_public_source_testnet_assurance_bundle',
    'build_public_source_testnet_assurance_verdict',
    'render_public_source_testnet_assurance_markdown',
    'validate_public_source_testnet_assurance_bundle',
    'validate_public_source_testnet_assurance_verdict',
]
