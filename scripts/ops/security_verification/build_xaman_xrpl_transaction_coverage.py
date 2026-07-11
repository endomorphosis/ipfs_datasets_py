#!/usr/bin/env python3
"""Build the Xaman XRPL transaction coverage artifact for PORTAL-CXTP-146."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
FACTS_PATH = CORPUS_DIR / 'xrpl-transaction-facts.json'
CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'
DISPROOF_VECTORS_PATH = CORPUS_DIR / 'disproof-vectors.json'
OUTPUT_PATH = CORPUS_DIR / 'xrpl-transaction-coverage.json'

SCHEMA_VERSION = 'xaman-xrpl-transaction-coverage/v1'
TASK_ID = 'PORTAL-CXTP-146'

REQUIRED_CONSTRAINTS = (
    'TrustSet',
    'OfferCreate',
    'SignerListSet',
    'payment',
    'issued_currency',
    'destination_tag',
    'fee',
    'sequence',
    'multisign',
    'memo',
    'network',
    'canonicalization',
)


def _load_json(repo_root: Path, path: Path) -> dict[str, Any]:
    return json.loads((repo_root / path).read_text(encoding='utf-8'))


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _with_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body['artifact_cid'] = _canonical_sha256(body)
    return body


def _by_id(entries: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(entry['id']): entry for entry in entries}


def _evidence_from(
    entry: Mapping[str, Any],
    *,
    source_artifact: str,
    fact_ids: list[str],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = [
        {
            'kind': 'source_model_artifact',
            'path': source_artifact,
            'fact_ids': fact_ids,
            'review_status': 'reviewed',
        }
    ]
    for evidence in entry.get('evidence', []):
        if isinstance(evidence, Mapping):
            refs.append(dict(evidence))
    return refs


def _constraint(
    *,
    constraint: str,
    status: str,
    proof_effect: str,
    summary: str,
    transaction_types: list[str],
    modeled_fields: list[str],
    rejected_conditions: list[str],
    gap_ids: list[str],
    counterexample_vector_ids: list[str],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'constraint': constraint,
        'status': status,
        'proof_effect': proof_effect,
        'summary': summary,
        'reachable_public_flow': True,
        'transaction_types': transaction_types,
        'modeled_fields_or_guards': modeled_fields,
        'explicitly_rejected_conditions': rejected_conditions,
        'coverage_gap_ids': gap_ids,
        'counterexample_vector_ids': counterexample_vector_ids,
        'evidence': evidence,
    }


def build_xrpl_transaction_coverage(repo_root: Path) -> dict[str, Any]:
    facts = _load_json(repo_root, FACTS_PATH)
    claims = _load_json(repo_root, CLAIMS_PATH)
    fact_by_id = _by_id(list(facts['modeled_facts']))
    gap_by_id = _by_id(list(facts['not_modeled_gaps']))
    source_artifact = FACTS_PATH.as_posix()

    common = fact_by_id[
        'xaman-xrpl-transaction:fact:common-fields-require-account-sequence-last-ledger'
    ]
    signing = fact_by_id[
        'xaman-xrpl-transaction:fact:signing-requires-fee-sequence-network-and-supported-type'
    ]
    payment_fields = fact_by_id[
        'xaman-xrpl-transaction:fact:payment-fields-bind-amount-destination-paths-and-delivered-amount'
    ]
    payment_validation = fact_by_id[
        'xaman-xrpl-transaction:fact:payment-validation-blocks-zero-native-overspend-and-trustline-failures'
    ]
    trustset = fact_by_id[
        'xaman-xrpl-transaction:fact:trustset-models-limit-currency-and-issuer'
    ]
    offercreate = fact_by_id[
        'xaman-xrpl-transaction:fact:offercreate-models-taker-amounts-rate-and-expiration'
    ]
    signerlist = fact_by_id[
        'xaman-xrpl-transaction:fact:signerlistset-models-quorum-and-signer-entries'
    ]
    memo = fact_by_id[
        'xaman-xrpl-transaction:fact:memo-parser-encodes-text-and-binary-memos'
    ]
    amount = fact_by_id[
        'xaman-xrpl-transaction:fact:amount-parser-normalizes-drops-and-native-values'
    ]
    dispatch = fact_by_id[
        'xaman-xrpl-transaction:fact:transaction-factory-dispatches-by-type-with-fallback'
    ]
    validation = fact_by_id[
        'xaman-xrpl-transaction:fact:validation-factory-dispatches-class-specific-validation'
    ]
    todo_gap = gap_by_id[
        'xaman-xrpl-transaction:gap:trustset-offercreate-signerlistset-validation-is-todo'
    ]
    full_coverage_gap = gap_by_id[
        'xaman-xrpl-transaction:gap:complete-xrpl-amendment-and-transaction-class-coverage'
    ]
    runtime_gap = gap_by_id[
        'xaman-xrpl-transaction:gap:ledger-service-network-service-runtime-trust'
    ]
    consensus_gap = gap_by_id[
        'xaman-xrpl-transaction:gap:ledger-consensus-finality-and-mempool-semantics'
    ]

    constraints = [
        _constraint(
            constraint='TrustSet',
            status='EXPLICITLY_REJECTED_FOR_PROOF',
            proof_effect='counterexample_required_if_treated_as_proved',
            summary='TrustSet class fields are modeled, but validation resolves without semantic checks; TrustSet user-intent safety is rejected for proof.',
            transaction_types=['TrustSet'],
            modeled_fields=['LimitAmount', 'Currency', 'Issuer', 'Limit'],
            rejected_conditions=[
                'LimitAmount semantic validation',
                'issuer trustline authorization',
                'trustline reserve and flag safety',
            ],
            gap_ids=[todo_gap['id']],
            counterexample_vector_ids=['xaman-disproof:unsupported-xrpl-semantics'],
            evidence=_evidence_from(
                trustset,
                source_artifact=source_artifact,
                fact_ids=[trustset['id'], todo_gap['id']],
            ),
        ),
        _constraint(
            constraint='OfferCreate',
            status='EXPLICITLY_REJECTED_FOR_PROOF',
            proof_effect='counterexample_required_if_treated_as_proved',
            summary='OfferCreate taker amount and rate presentation is modeled, but validation resolves without semantic checks; offer safety is rejected for proof.',
            transaction_types=['OfferCreate'],
            modeled_fields=['TakerPays', 'TakerGets', 'Expiration', 'OfferID', 'rate'],
            rejected_conditions=[
                'TakerPays/TakerGets spendability validation',
                'offer expiration safety',
                'cross-currency offer rule completeness',
            ],
            gap_ids=[todo_gap['id']],
            counterexample_vector_ids=['xaman-disproof:unsupported-xrpl-semantics'],
            evidence=_evidence_from(
                offercreate,
                source_artifact=source_artifact,
                fact_ids=[offercreate['id'], todo_gap['id']],
            ),
        ),
        _constraint(
            constraint='SignerListSet',
            status='EXPLICITLY_REJECTED_FOR_PROOF',
            proof_effect='counterexample_required_if_treated_as_proved',
            summary='SignerListSet quorum and entries are decoded, but validation resolves without semantic checks; signer-list safety is rejected for proof.',
            transaction_types=['SignerListSet'],
            modeled_fields=['SignerQuorum', 'SignerEntries'],
            rejected_conditions=[
                'quorum bounds validation',
                'signer weight validation',
                'signer-entry uniqueness and authorization',
            ],
            gap_ids=[todo_gap['id']],
            counterexample_vector_ids=['xaman-disproof:unsupported-xrpl-semantics'],
            evidence=_evidence_from(
                signerlist,
                source_artifact=source_artifact,
                fact_ids=[signerlist['id'], todo_gap['id']],
            ),
        ),
        _constraint(
            constraint='payment',
            status='MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS',
            proof_effect='not_a_standalone_proof_until_runtime_and_consensus_assumptions_clear',
            summary='Payment fields, native amount checks, issued-currency trustline checks, issuer freeze checks, and issuer obligation checks are modeled from source.',
            transaction_types=['Payment'],
            modeled_fields=[
                'Amount',
                'Destination',
                'DestinationTag',
                'SendMax',
                'DeliverMin',
                'Paths',
                'native available balance',
                'destination trustline',
            ],
            rejected_conditions=['path payment client-side validation is skipped'],
            gap_ids=[runtime_gap['id'], consensus_gap['id']],
            counterexample_vector_ids=[],
            evidence=_evidence_from(
                payment_validation,
                source_artifact=source_artifact,
                fact_ids=[payment_fields['id'], payment_validation['id']],
            ),
        ),
        _constraint(
            constraint='issued_currency',
            status='PARTIALLY_MODELED_AND_PARTIALLY_REJECTED',
            proof_effect='payment_issued_currency_checks_are_modeled_trustset_and_offercreate_are_not_proof_eligible',
            summary='Issued-currency Payment trustline and issuer checks are modeled; TrustSet and OfferCreate issued-currency semantics remain rejected because their validators are TODO pass-throughs.',
            transaction_types=['Payment', 'TrustSet', 'OfferCreate'],
            modeled_fields=['Payment Amount object', 'SendMax', 'issuer', 'currency', 'trustline', 'freeze'],
            rejected_conditions=[
                'TrustSet issued-currency validation',
                'OfferCreate issued-currency validation',
            ],
            gap_ids=[todo_gap['id'], runtime_gap['id']],
            counterexample_vector_ids=['xaman-disproof:unsupported-xrpl-semantics'],
            evidence=_evidence_from(
                payment_validation,
                source_artifact=source_artifact,
                fact_ids=[payment_validation['id'], trustset['id'], offercreate['id'], todo_gap['id']],
            ),
        ),
        _constraint(
            constraint='destination_tag',
            status='MODELED_FIELD_PRESERVATION',
            proof_effect='field_is_preserved_but_destination_tag_business_policy_is_not_proved',
            summary='Payment exposes DestinationTag as an optional field. The source-backed model preserves the field but does not prove exchange-specific tag policy correctness.',
            transaction_types=['Payment'],
            modeled_fields=['Destination', 'DestinationTag', 'InvoiceID'],
            rejected_conditions=['recipient-specific destination tag business policy'],
            gap_ids=[runtime_gap['id']],
            counterexample_vector_ids=[],
            evidence=_evidence_from(
                payment_fields,
                source_artifact=source_artifact,
                fact_ids=[payment_fields['id']],
            ),
        ),
        _constraint(
            constraint='fee',
            status='MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS',
            proof_effect='fee_guard_is_modeled_but_fee_freshness_depends_on_runtime_services',
            summary='Signing requires Fee before prepare and balance mutation display deducts the fee, but fee freshness and server fee policy are outside the client proof.',
            transaction_types=['common'],
            modeled_fields=['Fee', 'prepare requires fee', 'fee balance mutation'],
            rejected_conditions=['server fee policy correctness', 'runtime fee freshness'],
            gap_ids=[runtime_gap['id']],
            counterexample_vector_ids=[],
            evidence=_evidence_from(
                signing,
                source_artifact=source_artifact,
                fact_ids=[common['id'], signing['id']],
            ),
        ),
        _constraint(
            constraint='sequence',
            status='MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS',
            proof_effect='sequence_population_is_modeled_but_sequence_freshness_depends_on_runtime_services',
            summary='The model records required Sequence/LastLedgerSequence fields and SignMixin sequence population, while ledger freshness remains an explicit gap.',
            transaction_types=['common'],
            modeled_fields=['Sequence', 'LastLedgerSequence', 'TicketSequence'],
            rejected_conditions=['fresh ledger sequence source authenticity'],
            gap_ids=[runtime_gap['id']],
            counterexample_vector_ids=[],
            evidence=_evidence_from(
                signing,
                source_artifact=source_artifact,
                fact_ids=[common['id'], signing['id']],
            ),
        ),
        _constraint(
            constraint='multisign',
            status='EXPLICITLY_REJECTED_FOR_PROOF',
            proof_effect='counterexample_required_if_treated_as_proved',
            summary='Common Signers and SignerListSet fields are modeled, and SignMixin records that multisign skips prepare; signer-list semantic safety is rejected.',
            transaction_types=['SignerListSet', 'common'],
            modeled_fields=['Signers', 'SignerQuorum', 'SignerEntries', 'multisign_skips_prepare'],
            rejected_conditions=[
                'signer quorum safety',
                'signer entry validation',
                'multisign prepare-equivalence proof',
            ],
            gap_ids=[todo_gap['id']],
            counterexample_vector_ids=['xaman-disproof:unsupported-xrpl-semantics'],
            evidence=_evidence_from(
                signerlist,
                source_artifact=source_artifact,
                fact_ids=[common['id'], signing['id'], signerlist['id'], todo_gap['id']],
            ),
        ),
        _constraint(
            constraint='memo',
            status='MODELED',
            proof_effect='memo_parser_semantics_are_source_modeled',
            summary='Memo parsing distinguishes text/plain descriptions from application/x-binary reference memos and preserves binary memo data.',
            transaction_types=['common'],
            modeled_fields=['Memos', 'MemoData', 'MemoFormat', 'MemoType'],
            rejected_conditions=[],
            gap_ids=[],
            counterexample_vector_ids=[],
            evidence=_evidence_from(
                memo,
                source_artifact=source_artifact,
                fact_ids=[memo['id']],
            ),
        ),
        _constraint(
            constraint='network',
            status='MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS',
            proof_effect='client_network_guards_are_modeled_but_endpoint_and_consensus_trust_are_not_proved',
            summary='Signing rejects unsupported transaction types for current network definitions and writes NetworkID only for non-legacy network IDs greater than 1024.',
            transaction_types=['common'],
            modeled_fields=['NetworkID', 'unsupported transaction type rejection', 'current network definitions'],
            rejected_conditions=['NetworkService configuration authenticity', 'node endpoint network honesty'],
            gap_ids=[runtime_gap['id'], consensus_gap['id']],
            counterexample_vector_ids=['xaman-disproof:wrong-network-signing'],
            evidence=_evidence_from(
                signing,
                source_artifact=source_artifact,
                fact_ids=[signing['id']],
            ),
        ),
        _constraint(
            constraint='canonicalization',
            status='EXPLICITLY_REJECTED_FOR_FULL_XRPL_BINARY_PROOF',
            proof_effect='canonical_binary_signing_claims_must_remain_not_modeled_without_codec_and_vault_evidence',
            summary='Amount and memo normalization are modeled, but XRPL binary canonicalization and the vault-produced signed blob are not proved by the public TypeScript evidence.',
            transaction_types=['common', 'Payment'],
            modeled_fields=[
                'drops to native conversion',
                'native to drops conversion',
                'memo hex encoding',
                'signed tx_blob submit boundary',
            ],
            rejected_conditions=[
                'XRPL binary codec canonical serialization',
                'vault callback signed-byte equivalence',
                'canonical field ordering proof',
            ],
            gap_ids=[full_coverage_gap['id'], runtime_gap['id']],
            counterexample_vector_ids=[],
            evidence=_evidence_from(
                amount,
                source_artifact=source_artifact,
                fact_ids=[amount['id'], memo['id']],
            ),
        ),
    ]

    unsupported_policy = {
        'decision': 'RECORD_GAP_OR_COUNTEREXAMPLE_NEVER_PROOF',
        'fallback_transaction_proof_eligible': False,
        'unsupported_network_transaction_type_proof_eligible': False,
        'unsupported_type_handling': [
            {
                'condition': 'known class with TODO validation',
                'transaction_types': ['TrustSet', 'OfferCreate', 'SignerListSet'],
                'required_result': 'counterexample_found',
                'vector_id': 'xaman-disproof:unsupported-xrpl-semantics',
            },
            {
                'condition': 'fallback or amendment transaction outside reviewed coverage',
                'transaction_types': ['unreviewed_xrpl_transaction_type'],
                'required_result': 'coverage_gap',
                'gap_id': full_coverage_gap['id'],
            },
            {
                'condition': 'transaction type unsupported by current network definitions',
                'transaction_types': ['network_unsupported_transaction_type'],
                'required_result': 'client_rejects_before_signing',
                'fact_id': signing['id'],
            },
        ],
        'evidence': _evidence_from(
            dispatch,
            source_artifact=source_artifact,
            fact_ids=[dispatch['id'], validation['id'], signing['id'], full_coverage_gap['id']],
        ),
    }

    explicit_rejections = [
        row for row in constraints if row['status'].startswith('EXPLICITLY_REJECTED')
    ]
    modeled = [row for row in constraints if row['status'].startswith('MODELED')]
    partial = [row for row in constraints if row['status'].startswith('PARTIALLY')]

    payload: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'corpus': facts['corpus'],
        'source': {
            **facts['source'],
            'facts_path': FACTS_PATH.as_posix(),
            'claims_path': CLAIMS_PATH.as_posix(),
            'disproof_vectors_path': DISPROOF_VECTORS_PATH.as_posix(),
            'public_source_only': True,
        },
        'review': {
            'review_status': 'reviewed',
            'reviewed_at': '2026-07-11',
            'depends_on': ['PORTAL-CXTP-143', 'PORTAL-CXTP-144'],
            'acceptance_rule': 'Every reachable public XRPL flow is modeled, explicitly rejected, or recorded as a coverage gap/counterexample; unsupported transaction types never produce proof eligibility.',
        },
        'required_constraint_status': {
            constraint: next(
                row['status'] for row in constraints if row['constraint'] == constraint
            )
            for constraint in REQUIRED_CONSTRAINTS
        },
        'constraint_coverage': constraints,
        'reachable_public_flow_decisions': [
            {
                'flow_id': 'xaman-xrpl-flow:payment-review-sign-submit',
                'transaction_type': 'Payment',
                'decision': 'MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS',
                'claim_id': 'xaman-claim:payment-semantics-check-amount-balance-and-trustlines',
                'proof_eligible': False,
                'blocking_reason': 'LedgerService freshness, NetworkService authenticity, XRPL finality, and deployed runtime equivalence are not proved.',
            },
            {
                'flow_id': 'xaman-xrpl-flow:trustset-review-sign',
                'transaction_type': 'TrustSet',
                'decision': 'EXPLICITLY_REJECTED_FOR_PROOF',
                'claim_id': 'xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
                'proof_eligible': False,
                'blocking_reason': 'TrustSet validation is a TODO pass-through.',
            },
            {
                'flow_id': 'xaman-xrpl-flow:offercreate-review-sign',
                'transaction_type': 'OfferCreate',
                'decision': 'EXPLICITLY_REJECTED_FOR_PROOF',
                'claim_id': 'xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
                'proof_eligible': False,
                'blocking_reason': 'OfferCreate validation is a TODO pass-through.',
            },
            {
                'flow_id': 'xaman-xrpl-flow:signerlistset-review-sign',
                'transaction_type': 'SignerListSet',
                'decision': 'EXPLICITLY_REJECTED_FOR_PROOF',
                'claim_id': 'xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
                'proof_eligible': False,
                'blocking_reason': 'SignerListSet validation is a TODO pass-through and multisign prepare equivalence is not proved.',
            },
            {
                'flow_id': 'xaman-xrpl-flow:unsupported-or-unreviewed-type',
                'transaction_type': 'unreviewed_xrpl_transaction_type',
                'decision': 'COVERAGE_GAP_NEVER_PROOF',
                'claim_id': 'xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
                'proof_eligible': False,
                'blocking_reason': 'Complete XRPL amendment and transaction-class coverage is not established.',
            },
        ],
        'unsupported_transaction_policy': unsupported_policy,
        'coverage_gaps': [
            {
                'gap_id': gap['id'],
                'category': gap['category'],
                'summary': gap['summary'],
                'required_evidence_to_model': gap['required_evidence_to_model'],
                'proof_effect': 'blocks_proof',
            }
            for gap in [todo_gap, full_coverage_gap, runtime_gap, consensus_gap]
        ],
        'counterexample_bindings': [
            {
                'vector_id': 'xaman-disproof:unsupported-xrpl-semantics',
                'claim_id': 'xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
                'transaction_types': ['TrustSet', 'OfferCreate', 'SignerListSet'],
                'result_required': 'counterexample_found',
                'blocked_release_effect': 'block',
            },
            {
                'vector_id': 'xaman-disproof:wrong-network-signing',
                'claim_id': 'xaman-claim:network-binding-prevents-wrong-network-signing',
                'transaction_types': ['common'],
                'result_required': 'counterexample_found',
                'blocked_release_effect': 'block',
            },
        ],
        'claim_bindings': [
            {
                'claim_id': claim['id'],
                'status': claim['status'],
                'severity': claim['severity'],
                'assumptions': claim['assumptions'],
                'release_policy': claim['release_policy'],
            }
            for claim in claims['claims']
            if claim['category'] in {'transaction_semantics', 'network_binding'}
        ],
        'summary': {
            'required_constraint_count': len(REQUIRED_CONSTRAINTS),
            'modeled_constraint_count': len(modeled),
            'partial_constraint_count': len(partial),
            'explicit_rejection_count': len(explicit_rejections),
            'coverage_gap_count': 4,
            'proof_eligible_unsupported_type_count': 0,
            'production_release_approval_count': 0,
        },
        'overall_status': 'blocked',
        'production_release_blocked': True,
        'security_decision': 'BLOCK_UNSUPPORTED_OR_PARTIAL_XRPL_TRANSACTION_SEMANTICS',
    }
    return _with_artifact_cid(payload)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR))
    parser.add_argument('--out', default=OUTPUT_PATH.as_posix())
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    payload = build_xrpl_transaction_coverage(repo_root)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    _write_json(out_path, payload)
    print(
        f'Wrote {out_path.relative_to(repo_root)} '
        f'({payload["summary"]["required_constraint_count"]} constraints, '
        f'{payload["summary"]["explicit_rejection_count"]} explicit rejections)'
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
