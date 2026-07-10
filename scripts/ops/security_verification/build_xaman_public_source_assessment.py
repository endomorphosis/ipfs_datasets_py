#!/usr/bin/env python3
"""Build the Xaman public-source security assessment profile.

The profile is deliberately not a release approval. It separates public
source-backed evidence from conditional claims, counterexamples, unmodeled
components, solver gaps, external assumptions, and evidence that only Xaman or
other vendors can provide.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
DEFAULT_OUT = CORPUS_DIR / 'public-source-assessment.json'

SOURCE_MANIFEST_PATH = CORPUS_DIR / 'source-manifest.json'
SOURCE_COVERAGE_PATH = CORPUS_DIR / 'source-coverage.json'
WALLET_AUTH_PATH = CORPUS_DIR / 'wallet-auth-facts.json'
PAYLOAD_LIFECYCLE_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'
XRPL_TRANSACTION_PATH = CORPUS_DIR / 'xrpl-transaction-facts.json'
SECURITY_CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'
COUNTEREXAMPLE_REPORT_PATH = CORPUS_DIR / 'counterexample-report.json'
SMT_DIFFERENTIAL_PATH = CORPUS_DIR / 'proof-reports/z3-cvc5-differential.json'
TLA_APALACHE_PATH = CORPUS_DIR / 'tla/apalache-report.json'
PROTOCOL_REPORT_PATH = CORPUS_DIR / 'protocol/protocol-report.json'
RUNTIME_TRACE_PATH = CORPUS_DIR / 'runtime-trace-report.json'
PROOF_CONSUMER_REPORT_PATH = CORPUS_DIR / 'proof-kernel/proof-consumer-report.json'
ASSURANCE_PACKET_PATH = CORPUS_DIR / 'assurance-packet.json'

FACT_ARTIFACTS: tuple[tuple[str, Path], ...] = (
    ('wallet_auth', WALLET_AUTH_PATH),
    ('payload_lifecycle', PAYLOAD_LIFECYCLE_PATH),
    ('xrpl_transaction', XRPL_TRANSACTION_PATH),
)

PUBLIC_SOURCE_REVIEW_RESULT = 'blocked_public_source_assessment'
PUBLIC_SOURCE_SECURITY_DECISION = 'BLOCK_PUBLIC_SOURCE_ASSESSMENT_NOT_RELEASE_APPROVAL'
GENERATED_AT_UTC = '2026-07-10T00:00:00Z'

PROHIBITED_PUBLIC_SOURCE_LABELS = (
    'production_release_approval',
    'approved_for_production_release',
    'release_approved',
    'production_approved',
    'accept_as_secure_without_vendor_evidence',
)


def _load_json(repo_root: Path, path: Path) -> dict[str, Any]:
    return json.loads((repo_root / path).read_text(encoding='utf-8'))


def _sha256_file(repo_root: Path, path: Path) -> str:
    return 'sha256:' + hashlib.sha256((repo_root / path).read_bytes()).hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _artifact_ref(
    repo_root: Path,
    path: Path,
    payload: Mapping[str, Any],
    *,
    kind: str,
) -> dict[str, Any]:
    return {
        'kind': kind,
        'path': str(path),
        'schema_version': payload.get('schema_version'),
        'task_id': payload.get('task_id'),
        'overall_status': payload.get('overall_status'),
        'security_decision': payload.get('security_decision'),
        'sha256': _sha256_file(repo_root, path),
    }


def _evidence_refs(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for evidence in record.get('evidence', []):
        refs.append({key: value for key, value in evidence.items() if value is not None})
    return refs


def _fact_entries(
    *,
    source_model: str,
    artifact_path: Path,
    facts: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for fact in facts:
        entries.append(
            {
                'id': fact['id'],
                'source_model': source_model,
                'artifact_path': str(artifact_path),
                'status': fact.get('status'),
                'category': fact.get('category'),
                'summary': fact.get('summary'),
                'normalized_fact': fact.get('normalized_fact', {}),
                'evidence': _evidence_refs(fact),
                'public_source_support': 'source_supported_fact',
            }
        )
    return entries


def _gap_entries(
    *,
    source_model: str,
    artifact_path: Path,
    gaps: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for gap in gaps:
        entries.append(
            {
                'id': gap['id'],
                'source_model': source_model,
                'artifact_path': str(artifact_path),
                'status': gap.get('status', 'NOT_MODELED'),
                'severity': gap.get('severity', 'blocking'),
                'category': gap.get('category'),
                'summary': gap.get('summary'),
                'required_evidence_to_model': gap.get('required_evidence_to_model', []),
                'evidence': _evidence_refs(gap),
                'public_source_support': 'not_modeled_from_public_source',
            }
        )
    return entries


def _conditional_claims(claims_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for claim in claims_payload['claims']:
        entries.append(
            {
                'id': claim['id'],
                'category': claim.get('category'),
                'severity': claim.get('severity'),
                'source_status': claim.get('status'),
                'summary': claim.get('summary'),
                'assumptions': claim.get('assumptions', []),
                'evidence': claim.get('evidence', []),
                'release_policy': claim.get('release_policy'),
                'public_source_result': 'conditional_or_blocked_not_production_approval',
                'production_release_approval': False,
            }
        )
    return entries


def _known_counterexamples(counterexample_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for result in counterexample_payload['results']:
        if result.get('result') != 'counterexample_found':
            continue
        entries.append(
            {
                'vector_id': result['vector_id'],
                'claim_id': result['claim_id'],
                'result': result['result'],
                'counterexample': result.get('counterexample'),
                'release_policy': result.get('release_policy', 'block'),
                'public_source_result': 'known_counterexample_blocks_approval',
            }
        )
    return entries


def _missing_evidence_vectors(counterexample_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for result in counterexample_payload['results']:
        if result.get('result') != 'blocked_by_missing_evidence':
            continue
        entries.append(
            {
                'vector_id': result['vector_id'],
                'claim_id': result['claim_id'],
                'result': result['result'],
                'missing_evidence': result.get('missing_evidence', []),
                'release_policy': result.get('release_policy', 'block'),
                'public_source_result': 'blocked_by_vendor_or_runtime_evidence_gap',
            }
        )
    return entries


def _runtime_unmodeled_components(runtime_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for gap in runtime_payload.get('blocking_gaps', []):
        entries.append(
            {
                'id': f'xaman-runtime:gap:{gap["code"].lower().replace("_", "-")}',
                'source_model': 'runtime_trace',
                'artifact_path': str(RUNTIME_TRACE_PATH),
                'status': 'NOT_MODELED',
                'severity': 'blocking',
                'category': 'runtime_equivalence',
                'summary': gap.get('reason') or f'Missing runtime evidence for {gap["code"]}.',
                'required_evidence_to_model': gap.get('required_categories', []),
                'evidence': [],
                'public_source_support': 'not_modeled_from_public_source',
            }
        )
    return entries


def _external_assumptions(claims_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for assumption in claims_payload['assumptions']:
        entries.append(
            {
                'id': assumption['id'],
                'status': assumption.get('status'),
                'source': assumption.get('source'),
                'summary': assumption.get('summary'),
                'required_evidence_to_clear': assumption.get('required_evidence_to_clear', []),
                'public_source_result': 'external_assumption_not_cleared_by_public_source',
            }
        )
    return entries


def _solver_coverage_gaps(
    *,
    smt_payload: Mapping[str, Any],
    tla_payload: Mapping[str, Any],
    protocol_payload: Mapping[str, Any],
    proof_consumer_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    protocol_blockers = protocol_payload.get('blockers', [])
    protocol_missing = protocol_blockers[0].get('missing', []) if protocol_blockers else []
    coq_payload = proof_consumer_payload.get('coq', {})
    coq_missing = coq_payload.get('missing_executables', [])
    if not coq_missing and coq_payload.get('status') == 'unavailable':
        coq_missing = ['coqc']
    return [
        {
            'lane': 'smt_z3_cvc5',
            'artifact_path': str(SMT_DIFFERENTIAL_PATH),
            'overall_status': smt_payload.get('overall_status', 'blocked'),
            'security_decision': smt_payload.get('security_decision'),
            'blocked_claim_count': smt_payload.get('blocked_claim_count', 0),
            'agreement_failure_count': smt_payload.get('agreement_failure_count', 0),
            'coverage_gap': 'SMT agreement only detects blocked assumptions here; it is not a proof of production safety.',
            'public_source_result': 'solver_lane_blocks_or_does_not_approve',
        },
        {
            'lane': 'tla_apalache',
            'artifact_path': str(TLA_APALACHE_PATH),
            'overall_status': tla_payload.get('overall_status'),
            'security_decision': tla_payload.get('security_decision'),
            'covered_claim_ids': tla_payload.get('covered_claim_ids', []),
            'missing': tla_payload.get('apalache', {}).get('missing_executables', []),
            'coverage_gap': 'Apalache executable is unavailable, so TLA invariants have not been model checked.',
            'public_source_result': 'solver_lane_missing',
        },
        {
            'lane': 'protocol_tamarin_proverif',
            'artifact_path': str(PROTOCOL_REPORT_PATH),
            'overall_status': protocol_payload.get('overall_status'),
            'security_decision': protocol_payload.get('security_decision'),
            'covered_claim_ids': protocol_payload.get('covered_claim_ids', []),
            'missing': protocol_missing,
            'coverage_gap': 'Tamarin and ProVerif protocol checks have not run.',
            'public_source_result': 'solver_lane_missing',
        },
        {
            'lane': 'proof_consumer_kernel',
            'artifact_path': str(PROOF_CONSUMER_REPORT_PATH),
            'overall_status': proof_consumer_payload.get('overall_status'),
            'security_decision': proof_consumer_payload.get('security_decision'),
            'covered_claim_ids': [proof_consumer_payload.get('claim_id')],
            'missing': coq_missing,
            'coverage_gap': 'Lean policy fixture is checked, but Coq is unavailable and production integration remains unproved.',
            'public_source_result': 'proof_consumer_not_production_integrated',
        },
    ]


def _vendor_only_evidence(
    assumptions: Iterable[Mapping[str, Any]],
    missing_vectors: Iterable[Mapping[str, Any]],
    assurance_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for assumption in assumptions:
        for evidence in assumption.get('required_evidence_to_clear', []):
            key = f'{assumption["id"]}:{evidence}'
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    'id': key,
                    'source': assumption['id'],
                    'required_evidence': evidence,
                    'availability': 'vendor_or_operator_only_until_provided',
                    'public_source_result': 'absent_from_public_source',
                }
            )
    for vector in missing_vectors:
        for evidence in vector.get('missing_evidence', []):
            key = f'{vector["vector_id"]}:{evidence}'
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    'id': key,
                    'source': vector['vector_id'],
                    'required_evidence': evidence,
                    'availability': 'vendor_or_operator_only_until_provided',
                    'public_source_result': 'absent_from_public_source',
                }
            )
    for index, evidence in enumerate(assurance_payload.get('next_required_evidence', []), start=1):
        key = f'xaman-assurance-next-evidence:{index}'
        if key in seen:
            continue
        entries.append(
            {
                'id': key,
                'source': str(ASSURANCE_PACKET_PATH),
                'required_evidence': evidence,
                'availability': 'vendor_or_operator_only_until_provided',
                'public_source_result': 'absent_from_public_source',
            }
        )
    return entries


def build_assessment(repo_root: Path) -> dict[str, Any]:
    manifest = _load_json(repo_root, SOURCE_MANIFEST_PATH)
    coverage = _load_json(repo_root, SOURCE_COVERAGE_PATH)
    claims = _load_json(repo_root, SECURITY_CLAIMS_PATH)
    counterexamples = _load_json(repo_root, COUNTEREXAMPLE_REPORT_PATH)
    smt = _load_json(repo_root, SMT_DIFFERENTIAL_PATH)
    tla = _load_json(repo_root, TLA_APALACHE_PATH)
    protocol = _load_json(repo_root, PROTOCOL_REPORT_PATH)
    runtime = _load_json(repo_root, RUNTIME_TRACE_PATH)
    proof_consumer = _load_json(repo_root, PROOF_CONSUMER_REPORT_PATH)
    assurance = _load_json(repo_root, ASSURANCE_PACKET_PATH)

    source_supported_facts: list[dict[str, Any]] = []
    unmodeled_components: list[dict[str, Any]] = []
    public_artifacts: list[dict[str, Any]] = [
        _artifact_ref(repo_root, SOURCE_MANIFEST_PATH, manifest, kind='source_manifest'),
        _artifact_ref(repo_root, SOURCE_COVERAGE_PATH, coverage, kind='source_coverage'),
    ]

    for source_model, artifact_path in FACT_ARTIFACTS:
        artifact = _load_json(repo_root, artifact_path)
        public_artifacts.append(
            _artifact_ref(repo_root, artifact_path, artifact, kind=f'{source_model}_facts')
        )
        source_supported_facts.extend(
            _fact_entries(
                source_model=source_model,
                artifact_path=artifact_path,
                facts=artifact.get('modeled_facts', []),
            )
        )
        unmodeled_components.extend(
            _gap_entries(
                source_model=source_model,
                artifact_path=artifact_path,
                gaps=artifact.get('not_modeled_gaps', []),
            )
        )

    public_artifacts.extend(
        [
            _artifact_ref(repo_root, SECURITY_CLAIMS_PATH, claims, kind='security_claims'),
            _artifact_ref(repo_root, COUNTEREXAMPLE_REPORT_PATH, counterexamples, kind='counterexamples'),
            _artifact_ref(repo_root, SMT_DIFFERENTIAL_PATH, smt, kind='smt_differential'),
            _artifact_ref(repo_root, TLA_APALACHE_PATH, tla, kind='tla_apalache'),
            _artifact_ref(repo_root, PROTOCOL_REPORT_PATH, protocol, kind='protocol_projection'),
            _artifact_ref(repo_root, RUNTIME_TRACE_PATH, runtime, kind='runtime_trace'),
            _artifact_ref(repo_root, PROOF_CONSUMER_REPORT_PATH, proof_consumer, kind='proof_consumer'),
            _artifact_ref(repo_root, ASSURANCE_PACKET_PATH, assurance, kind='assurance_packet'),
        ]
    )

    conditional_claims = _conditional_claims(claims)
    known_counterexamples = _known_counterexamples(counterexamples)
    missing_evidence_vectors = _missing_evidence_vectors(counterexamples)
    unmodeled_components.extend(_runtime_unmodeled_components(runtime))
    external_assumptions = _external_assumptions(claims)
    solver_gaps = _solver_coverage_gaps(
        smt_payload=smt,
        tla_payload=tla,
        protocol_payload=protocol,
        proof_consumer_payload=proof_consumer,
    )
    vendor_only_evidence = _vendor_only_evidence(
        external_assumptions,
        missing_evidence_vectors,
        assurance,
    )

    payload: dict[str, Any] = {
        'schema_version': 'xaman-public-source-assessment/v1',
        'task_id': 'PORTAL-CXTP-119',
        'corpus': 'xaman-app',
        'generated_at_utc': GENERATED_AT_UTC,
        'source': {
            'repo_url': manifest['source']['repo_url'],
            'commit_sha': manifest['source']['commit_sha'],
            'requested_ref': manifest['source'].get('requested_ref'),
            'manifest_path': str(SOURCE_MANIFEST_PATH),
            'manifest_schema_version': manifest.get('schema_version'),
            'coverage_path': str(SOURCE_COVERAGE_PATH),
            'coverage_aggregate_sha256': coverage.get('source', {}).get('aggregate_sha256'),
            'public_source_only': True,
        },
        'assessment_boundary': {
            'scope': 'public_source_security_assessment',
            'not_a_production_release_approval': True,
            'may_be_used_for_production_release_approval': False,
            'requires_vendor_or_operator_evidence_before_release_use': True,
            'prohibited_public_source_labels': list(PROHIBITED_PUBLIC_SOURCE_LABELS),
        },
        'public_source_artifacts': public_artifacts,
        'source_supported_facts': source_supported_facts,
        'conditional_claims': conditional_claims,
        'known_counterexamples': known_counterexamples,
        'missing_evidence_disproof_vectors': missing_evidence_vectors,
        'unmodeled_components': unmodeled_components,
        'external_assumptions': external_assumptions,
        'solver_coverage_gaps': solver_gaps,
        'vendor_only_evidence': vendor_only_evidence,
        'summary': {
            'source_supported_fact_count': len(source_supported_facts),
            'conditional_claim_count': len(conditional_claims),
            'known_counterexample_count': len(known_counterexamples),
            'missing_evidence_disproof_vector_count': len(missing_evidence_vectors),
            'unmodeled_component_count': len(unmodeled_components),
            'external_assumption_count': len(external_assumptions),
            'solver_coverage_gap_count': len(solver_gaps),
            'vendor_only_evidence_count': len(vendor_only_evidence),
            'proved_public_source_claim_count': 0,
            'production_release_approval_count': 0,
        },
        'public_source_result': PUBLIC_SOURCE_REVIEW_RESULT,
        'overall_status': 'blocked',
        'security_decision': PUBLIC_SOURCE_SECURITY_DECISION,
        'production_release_approval': False,
        'production_release_blocked': True,
        'release_decision': 'not_a_release_decision_public_source_only',
        'fail_closed_policy': {
            'default_action': 'block',
            'acceptance_rule': 'Public source evidence may support facts and conditional claims only; it must never approve a production release without cleared assumptions, vendor evidence, runtime traces, and required solver coverage.',
            'reject_public_source_results': [
                'proved_without_vendor_evidence',
                'solver_unknown',
                'missing_solver',
                'blocked_assumption',
                'known_counterexample',
                'unmodeled_component',
                'vendor_only_evidence_absent',
            ],
        },
    }
    payload['artifact_cid'] = _canonical_sha256(payload)
    return payload


def generate(repo_root: Path, out_path: Path) -> dict[str, Any]:
    assessment = build_assessment(repo_root)
    _write_json(out_path, assessment)
    return assessment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    parser.add_argument(
        '--out',
        default=str(DEFAULT_OUT),
        help='Output path for the public-source assessment JSON.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    assessment = generate(repo_root, out_path)
    print(
        'Wrote '
        f'{out_path.relative_to(repo_root)} '
        f'({assessment["summary"]["source_supported_fact_count"]} facts, '
        f'{assessment["summary"]["conditional_claim_count"]} conditional claims, '
        f'{assessment["summary"]["known_counterexample_count"]} counterexamples, '
        f'decision {assessment["security_decision"]})'
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
