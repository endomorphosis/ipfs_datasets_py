#!/usr/bin/env python3
"""Audit code-to-IR evidence coverage for crypto-exchange security claims."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.assumption_registry import (  # noqa: E402
    evaluate_assumption_registry,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import default_claims  # noqa: E402
from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import SourceCodeExtractor  # noqa: E402
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid  # noqa: E402
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import (  # noqa: E402
    example_minimal_exchange_model,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (  # noqa: E402
    SecurityModelIR,
    as_security_model_ir,
    collect_evidence_refs,
    evidence_review_statuses,
    validate_ir,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import (  # noqa: E402
    CLAIM_DOMAINS,
    prove_claims,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import (  # noqa: E402
    PROOF_RISK_BLOCKING,
    PROOF_RISK_HIGH,
    ProofReport,
)


AUDIT_SCHEMA_VERSION = 'code-to-ir-coverage/v1'
REVIEWED_STATUSES = frozenset({'human_reviewed', 'trusted_fixture'})
CRITICAL_RISKS = frozenset({PROOF_RISK_BLOCKING, PROOF_RISK_HIGH})
REQUIRED_COVERAGE_DOMAINS = (
    'wallets',
    'withdrawals',
    'deposits',
    'ledger',
    'capabilities',
    'hsm',
    'audit',
    'assumptions',
    'evidence_refs',
)
SECONDARY_CLAIM_DOMAINS = {
    'no_signing_request_after_wallet_freeze': ('wallets',),
}
SOURCE_EVIDENCE_KINDS = frozenset({'source_code', 'openapi', 'test_fixture'})
RUNTIME_EVIDENCE_KINDS = frozenset({'audit_log', 'test_fixture'})
POLICY_EVIDENCE_KINDS = frozenset({'policy_doc', 'manual_review', 'test_fixture'})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _load_model(args: argparse.Namespace) -> SecurityModelIR:
    if args.source_path:
        return validate_ir(
            SourceCodeExtractor().extract_ir_from_path(
                args.source_path,
                model_id=args.source_model_id,
            )
        )
    if args.model:
        return validate_ir(SecurityModelIR.from_untrusted_dict(json.loads(Path(args.model).read_text(encoding='utf-8'))))
    return validate_ir(example_minimal_exchange_model())


def _load_reports(path: str | None) -> list[ProofReport] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    raw_reports = payload.get('reports') if isinstance(payload, Mapping) else None
    if not isinstance(raw_reports, list):
        raise ValueError('proof report input must contain a reports list')
    return [ProofReport.from_dict(item) for item in raw_reports if isinstance(item, Mapping)]


def _prove_reports(model: SecurityModelIR) -> list[ProofReport]:
    return prove_claims(model, ['z3'])


def _as_report_dict(report: ProofReport | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(report, ProofReport):
        return report.to_dict()
    return dict(report)


def _dedupe_refs(refs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        normalized = dict(ref)
        key = json.dumps(normalized, sort_keys=True, default=str)
        if key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped


def _reviewed(ref: Mapping[str, Any]) -> bool:
    return str(ref.get('review_status', '')).strip().lower() in REVIEWED_STATUSES


def _evidence_path_status(evidence_refs: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    refs = _dedupe_refs(evidence_refs)
    reviewed_refs = [ref for ref in refs if _reviewed(ref)]
    reviewed_kinds = {str(ref.get('kind', '')).strip().lower() for ref in reviewed_refs}
    statuses = sorted(evidence_review_statuses(refs))
    has_reviewed_source = bool(reviewed_kinds.intersection(SOURCE_EVIDENCE_KINDS))
    has_reviewed_runtime = bool(reviewed_kinds.intersection(RUNTIME_EVIDENCE_KINDS))
    has_reviewed_policy = bool(reviewed_kinds.intersection(POLICY_EVIDENCE_KINDS))
    return {
        'total_refs': len(refs),
        'reviewed_refs': len(reviewed_refs),
        'review_statuses': statuses,
        'reviewed_kinds': sorted(reviewed_kinds),
        'has_reviewed_source': has_reviewed_source,
        'has_reviewed_runtime': has_reviewed_runtime,
        'has_reviewed_policy': has_reviewed_policy,
        'has_reviewed_evidence_path': has_reviewed_source or has_reviewed_runtime or has_reviewed_policy,
    }


def _policy_records(model: SecurityModelIR, names: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(names)
    return [dict(policy) for policy in model.policies if policy.get('name') in wanted]


def _events(model: SecurityModelIR, names: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(names)
    return [dict(event) for event in model.events if event.get('event') in wanted]


def _ledger_metadata_records(model: SecurityModelIR) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    ledger_totals = model.metadata.get('ledger_totals')
    if isinstance(ledger_totals, Mapping):
        records.append({'id': 'metadata.ledger_totals', 'ledger_totals': dict(ledger_totals)})
    refs = model.metadata.get('ledger_totals_evidence_refs')
    if isinstance(refs, list):
        records.append({'id': 'metadata.ledger_totals_evidence_refs', 'evidence_refs': refs})
    return records


def _domain_records(model: SecurityModelIR, domain: str) -> list[dict[str, Any]]:
    if domain == 'wallets':
        return [
            *[dict(wallet) for wallet in model.wallets],
            *_events(model, {'wallet_frozen', 'wallet_unfrozen'}),
        ]
    if domain == 'withdrawals':
        return [
            *_events(
                model,
                {
                    'withdrawal_requested',
                    'withdrawal_approved',
                    'withdrawal_broadcast',
                    'withdrawal_cancelled',
                    'balance_reserved',
                    'balance_released',
                    'nonce_reserved',
                    'nonce_consumed',
                },
            ),
            *_policy_records(
                model,
                {
                    'authorization_required',
                    'fresh_nonce_required',
                    'sufficient_balance_required',
                    'wallet_not_frozen_required',
                    'atomic_reservation',
                },
            ),
        ]
    if domain == 'deposits':
        return [
            *_events(
                model,
                {
                    'deposit_observed',
                    'deposit_finalized',
                    'deposit_credited',
                    'chain_reorg_detected',
                },
            ),
            *_policy_records(model, {'credit_after_finality_required'}),
        ]
    if domain == 'ledger':
        return [
            *[dict(asset) for asset in model.assets],
            *[dict(account) for account in model.accounts],
            *_events(model, {'balance_reserved', 'balance_released'}),
            *_policy_records(model, {'atomic_reservation'}),
            *_ledger_metadata_records(model),
        ]
    if domain == 'capabilities':
        return [
            *[dict(capability) for capability in model.capabilities],
            *_events(
                model,
                {'capability_revoked', 'capability_reinstated', 'privileged_action'},
            ),
            *_policy_records(model, {'delegation_monotonicity', 'revocation_enforced'}),
        ]
    if domain == 'hsm':
        return [
            *[dict(wallet) for wallet in model.wallets],
            *_events(model, {'signing_request', 'wallet_frozen', 'wallet_unfrozen'}),
            *_policy_records(model, {'wallet_not_frozen_required'}),
        ]
    if domain == 'audit':
        return [
            *_events(model, {'audit_logged'}),
            *[dict(event) for event in model.events if event.get('critical')],
            *_policy_records(model, {'audit_required'}),
        ]
    if domain == 'assumptions':
        return [dict(item) if isinstance(item, Mapping) else {'id': item} for item in model.assumptions]
    if domain == 'evidence_refs':
        return [{'id': f'evidence_ref:{index}', 'evidence_refs': [ref]} for index, ref in enumerate(all_model_evidence_refs(model))]
    raise ValueError(f'unsupported coverage domain: {domain}')


def all_model_evidence_refs(model: SecurityModelIR) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for collection in (
        model.entities,
        model.assets,
        model.wallets,
        model.accounts,
        model.roles,
        model.principals,
        model.capabilities,
        model.policies,
        model.events,
        model.state_machines,
        model.invariants,
    ):
        refs.extend(collect_evidence_refs(*collection))
    for assumption in model.assumptions:
        if isinstance(assumption, Mapping):
            refs.extend(collect_evidence_refs(assumption))
    for key in ('ledger_totals_evidence_refs',):
        value = model.metadata.get(key)
        if isinstance(value, list):
            refs.extend(dict(ref) for ref in value if isinstance(ref, Mapping))
    autoformalization = model.metadata.get('autoformalization')
    if isinstance(autoformalization, Mapping):
        refs.extend(collect_evidence_refs(autoformalization))
    return _dedupe_refs(refs)


def _domain_summary(model: SecurityModelIR, reports: list[dict[str, Any]]) -> dict[str, Any]:
    reports_by_domain: dict[str, list[dict[str, Any]]] = {domain: [] for domain in REQUIRED_COVERAGE_DOMAINS}
    for report in reports:
        claim_id = str(report.get('claim_id', ''))
        domain = CLAIM_DOMAINS.get(claim_id)
        if domain in reports_by_domain:
            reports_by_domain[domain].append(report)
        for secondary_domain in SECONDARY_CLAIM_DOMAINS.get(claim_id, ()):
            if secondary_domain in reports_by_domain:
                reports_by_domain[secondary_domain].append(report)

    summary: dict[str, Any] = {}
    for domain in REQUIRED_COVERAGE_DOMAINS:
        records = _domain_records(model, domain)
        evidence_refs = all_model_evidence_refs(model) if domain == 'evidence_refs' else collect_evidence_refs(*records)
        path_status = _evidence_path_status(evidence_refs)
        domain_claims = reports_by_domain.get(domain, [])
        critical_claims = [report for report in domain_claims if report.get('risk') in CRITICAL_RISKS]
        summary[domain] = {
            'modeled': bool(records) if domain not in {'evidence_refs'} else bool(evidence_refs),
            'record_count': len(records),
            'evidence_ref_count': len(evidence_refs),
            'reviewed_evidence_ref_count': path_status['reviewed_refs'],
            'evidence_path_status': path_status,
            'claim_count': len(domain_claims),
            'critical_claim_count': len(critical_claims),
            'claim_ids': [str(report.get('claim_id', '')) for report in domain_claims],
        }
    return summary


def _claim_rows(reports: Iterable[ProofReport | Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report in reports:
        payload = _as_report_dict(report)
        evidence_refs = [dict(ref) for ref in payload.get('evidence_refs', []) if isinstance(ref, Mapping)]
        rows.append(
            {
                'claim_id': payload.get('claim_id', ''),
                'domain': CLAIM_DOMAINS.get(str(payload.get('claim_id', '')), 'unmapped'),
                'status': payload.get('status', ''),
                'risk': payload.get('risk', ''),
                'assumptions': list(payload.get('assumptions', [])) if isinstance(payload.get('assumptions'), list) else [],
                'evidence_refs': evidence_refs,
                'evidence_path_status': _evidence_path_status(evidence_refs),
                'soundness_notes': list(payload.get('soundness_notes', [])) if isinstance(payload.get('soundness_notes'), list) else [],
            }
        )
    return rows


def _evidence_ref_summary(refs: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = Counter(str(ref.get('kind', 'unknown')) for ref in refs)
    by_status = Counter(str(ref.get('review_status', 'unknown')) for ref in refs)
    path_status = _evidence_path_status(refs)
    return {
        'total': len(refs),
        'reviewed': path_status['reviewed_refs'],
        'by_kind': dict(sorted(by_kind.items())),
        'by_review_status': dict(sorted(by_status.items())),
        'path_status': path_status,
        'refs': refs,
    }


def _critical_evidence_failures(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for claim in claims:
        if claim.get('risk') not in CRITICAL_RISKS:
            continue
        path_status = claim.get('evidence_path_status', {})
        if isinstance(path_status, Mapping) and bool(path_status.get('has_reviewed_evidence_path')):
            continue
        failures.append(
            {
                'claim_id': claim.get('claim_id', ''),
                'domain': claim.get('domain', 'unmapped'),
                'risk': claim.get('risk', ''),
                'status': claim.get('status', ''),
                'reason': 'blocking/high claim has no reviewed source, runtime, or policy evidence path',
                'review_statuses': path_status.get('review_statuses', []) if isinstance(path_status, Mapping) else [],
                'evidence_ref_count': path_status.get('total_refs', 0) if isinstance(path_status, Mapping) else 0,
            }
        )
    return failures


def build_coverage_matrix(
    model: SecurityModelIR | Mapping[str, Any],
    reports: Iterable[ProofReport | Mapping[str, Any]] | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Return a machine-readable code-to-IR evidence coverage matrix."""

    normalized = validate_ir(as_security_model_ir(model))
    report_objects = list(_prove_reports(normalized) if reports is None else reports)
    claim_rows = _claim_rows(report_objects)
    evidence_refs = all_model_evidence_refs(normalized)
    claim_evidence_refs = _dedupe_refs(
        ref
        for claim in claim_rows
        for ref in claim.get('evidence_refs', [])
        if isinstance(ref, Mapping)
    )
    all_refs = _dedupe_refs([*evidence_refs, *claim_evidence_refs])
    failures = _critical_evidence_failures(claim_rows)
    assumption_registry = evaluate_assumption_registry(
        normalized,
        required_assumptions=sorted(
            {
                assumption
                for claim in claim_rows
                for assumption in claim.get('assumptions', [])
                if isinstance(assumption, str) and assumption.strip()
            },
            key=lambda item: (item[:1], int(item[1:]) if item[1:].isdigit() else item[1:]),
        ),
    )
    return {
        'schema_version': AUDIT_SCHEMA_VERSION,
        'generated_at': generated_at or _utc_now(),
        'model_id': normalized.model_id,
        'model_cid': calculate_model_cid(normalized),
        'release_ready': not failures,
        'required_domains': list(REQUIRED_COVERAGE_DOMAINS),
        'domains': _domain_summary(normalized, claim_rows),
        'claims': claim_rows,
        'assumptions': assumption_registry,
        'evidence_refs': _evidence_ref_summary(all_refs),
        'failures': failures,
        'policy': {
            'critical_risks': sorted(CRITICAL_RISKS),
            'reviewed_statuses': sorted(REVIEWED_STATUSES),
            'fail_closed_rule': 'blocking/high claims require at least one reviewed source, runtime, or policy evidence path',
        },
    }


def render_markdown(matrix: Mapping[str, Any]) -> str:
    domains = matrix.get('domains', {})
    claims = matrix.get('claims', [])
    failures = matrix.get('failures', [])
    evidence_refs = matrix.get('evidence_refs', {})
    assumptions = matrix.get('assumptions', {})
    lines = [
        '# Code-to-IR Evidence Coverage Matrix',
        '',
        f'Generated: `{matrix.get("generated_at", "")}`',
        '',
        f'- Model: `{matrix.get("model_id", "")}`',
        f'- Model CID: `{matrix.get("model_cid", "")}`',
        f'- Release ready for evidence coverage: `{matrix.get("release_ready", False)}`',
        f'- Failures: `{len(failures) if isinstance(failures, list) else 0}`',
        '',
        '## Domain Coverage',
        '',
        '| Domain | Modeled | Records | Claims | Critical Claims | Evidence Refs | Reviewed Refs | Reviewed Path |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |',
    ]
    if isinstance(domains, Mapping):
        for domain in REQUIRED_COVERAGE_DOMAINS:
            summary = domains.get(domain, {})
            path_status = summary.get('evidence_path_status', {}) if isinstance(summary, Mapping) else {}
            lines.append(
                '| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` |'.format(
                    domain,
                    bool(summary.get('modeled')) if isinstance(summary, Mapping) else False,
                    summary.get('record_count', 0) if isinstance(summary, Mapping) else 0,
                    summary.get('claim_count', 0) if isinstance(summary, Mapping) else 0,
                    summary.get('critical_claim_count', 0) if isinstance(summary, Mapping) else 0,
                    summary.get('evidence_ref_count', 0) if isinstance(summary, Mapping) else 0,
                    summary.get('reviewed_evidence_ref_count', 0) if isinstance(summary, Mapping) else 0,
                    bool(path_status.get('has_reviewed_evidence_path')) if isinstance(path_status, Mapping) else False,
                )
            )
    lines.extend(
        [
            '',
            '## Claim Evidence',
            '',
            '| Claim | Domain | Risk | Status | Assumptions | Evidence Refs | Reviewed Source | Reviewed Runtime | Reviewed Policy |',
            '| --- | --- | --- | --- | --- | ---: | --- | --- | --- |',
        ]
    )
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            path_status = claim.get('evidence_path_status', {})
            assumptions_text = ', '.join(str(item) for item in claim.get('assumptions', []))
            lines.append(
                '| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` |'.format(
                    claim.get('claim_id', ''),
                    claim.get('domain', ''),
                    claim.get('risk', ''),
                    claim.get('status', ''),
                    assumptions_text,
                    path_status.get('total_refs', 0) if isinstance(path_status, Mapping) else 0,
                    bool(path_status.get('has_reviewed_source')) if isinstance(path_status, Mapping) else False,
                    bool(path_status.get('has_reviewed_runtime')) if isinstance(path_status, Mapping) else False,
                    bool(path_status.get('has_reviewed_policy')) if isinstance(path_status, Mapping) else False,
                )
            )
    summary = assumptions.get('summary', {}) if isinstance(assumptions, Mapping) else {}
    lines.extend(
        [
            '',
            '## Assumptions',
            '',
            f'- Assumption evidence ready: `{assumptions.get("release_ready", False) if isinstance(assumptions, Mapping) else False}`',
            f'- Required assumptions: `{summary.get("total", 0) if isinstance(summary, Mapping) else 0}`',
            f'- Owned: `{summary.get("owned", 0) if isinstance(summary, Mapping) else 0}`',
            f'- Evidenced: `{summary.get("evidenced", 0) if isinstance(summary, Mapping) else 0}`',
            f'- Current: `{summary.get("current", 0) if isinstance(summary, Mapping) else 0}`',
            '',
            '## Evidence References',
            '',
            f'- Total refs: `{evidence_refs.get("total", 0) if isinstance(evidence_refs, Mapping) else 0}`',
            f'- Reviewed refs: `{evidence_refs.get("reviewed", 0) if isinstance(evidence_refs, Mapping) else 0}`',
            f'- By kind: `{json.dumps(evidence_refs.get("by_kind", {}), sort_keys=True) if isinstance(evidence_refs, Mapping) else "{}"}`',
            f'- By review status: `{json.dumps(evidence_refs.get("by_review_status", {}), sort_keys=True) if isinstance(evidence_refs, Mapping) else "{}"}`',
            '',
            '## Fail-Closed Rule',
            '',
            'Any blocking or high-risk claim without at least one `human_reviewed` or `trusted_fixture` source, runtime, or policy evidence path fails this audit.',
        ]
    )
    if failures:
        lines.extend(['', '## Failures', ''])
        for failure in failures:
            if isinstance(failure, Mapping):
                lines.append(f'- `{failure.get("claim_id", "")}`: {failure.get("reason", "")}')
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', action='store_true', help='Use the built-in example security model')
    parser.add_argument('--model', help='Path to a canonical SecurityModelIR JSON file')
    parser.add_argument('--source-path', help='Autoformalize a supported source file or directory before auditing')
    parser.add_argument('--source-model-id', help='Optional model_id override when using --source-path')
    parser.add_argument('--proof-report', help='Optional existing proof report JSON to audit instead of running Z3')
    parser.add_argument('--out', help='Path to write the JSON coverage matrix')
    parser.add_argument('--markdown-out', help='Optional path to write a Markdown coverage matrix')
    args = parser.parse_args(argv)

    if sum(bool(value) for value in (args.example, args.model, args.source_path)) > 1:
        parser.error('choose only one input: --example, --model, or --source-path')

    try:
        model = _load_model(args)
        reports = _load_reports(args.proof_report)
        matrix = build_coverage_matrix(model, reports)
    except ValueError as exc:
        parser.error(str(exc))

    rendered = json.dumps(matrix, indent=2, sort_keys=True)
    if args.out:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + '\n', encoding='utf-8')
    else:
        print(rendered)
    if args.markdown_out:
        markdown_path = Path(args.markdown_out)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(matrix), encoding='utf-8')
    return 0 if bool(matrix.get('release_ready')) else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
