import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
FACTS_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'xrpl-transaction-facts.json'
)
MANIFEST_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-manifest.json'
)
COVERAGE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-coverage.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_xrpl_transaction_model.md'


REQUIRED_CATEGORIES = {
    'account_field',
    'destination_field',
    'amount_semantics',
    'fee_sequence_network',
    'memo_semantics',
    'issued_currency_trustline',
    'multisign_semantics',
    'transaction_type_dispatch',
    'validation_dispatch',
    'broadcast_submit',
    'balance_mutation',
}

REQUIRED_FACT_IDS = {
    'xaman-xrpl-transaction:fact:common-fields-require-account-sequence-last-ledger',
    'xaman-xrpl-transaction:fact:transaction-factory-dispatches-by-type-with-fallback',
    'xaman-xrpl-transaction:fact:validation-factory-dispatches-class-specific-validation',
    'xaman-xrpl-transaction:fact:signing-requires-fee-sequence-network-and-supported-type',
    'xaman-xrpl-transaction:fact:payment-fields-bind-amount-destination-paths-and-delivered-amount',
    'xaman-xrpl-transaction:fact:payment-validation-blocks-zero-native-overspend-and-trustline-failures',
    'xaman-xrpl-transaction:fact:trustset-models-limit-currency-and-issuer',
    'xaman-xrpl-transaction:fact:offercreate-models-taker-amounts-rate-and-expiration',
    'xaman-xrpl-transaction:fact:signerlistset-models-quorum-and-signer-entries',
    'xaman-xrpl-transaction:fact:memo-parser-encodes-text-and-binary-memos',
    'xaman-xrpl-transaction:fact:amount-parser-normalizes-drops-and-native-values',
    'xaman-xrpl-transaction:fact:mutations-remove-fee-from-balance-changes',
    'xaman-xrpl-transaction:fact:submit-boundary-is-signed-blob-preliminary-ledger-result',
}

REQUIRED_GAP_IDS = {
    'xaman-xrpl-transaction:gap:trustset-offercreate-signerlistset-validation-is-todo',
    'xaman-xrpl-transaction:gap:complete-xrpl-amendment-and-transaction-class-coverage',
    'xaman-xrpl-transaction:gap:ledger-service-network-service-runtime-trust',
    'xaman-xrpl-transaction:gap:ledger-consensus-finality-and-mempool-semantics',
    'xaman-xrpl-transaction:gap:deployed-runtime-equivalence',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _manifest_files() -> dict[str, dict[str, Any]]:
    manifest = _load_json(MANIFEST_PATH)
    return {entry['path']: entry for entry in manifest['files']}


def _coverage_modules() -> dict[str, dict[str, Any]]:
    coverage = _load_json(COVERAGE_PATH)
    return {entry['path']: entry for entry in coverage['security_relevant_modules']}


def test_xaman_xrpl_transaction_schema_and_source_pin() -> None:
    facts = _load_json(FACTS_PATH)
    manifest = _load_json(MANIFEST_PATH)
    coverage = _load_json(COVERAGE_PATH)

    assert facts['schema_version'] == 'xaman-xrpl-transaction-facts/v1'
    assert facts['task_id'] == 'PORTAL-CXTP-066'
    assert facts['corpus'] == 'xaman-app'
    assert facts['source']['repo_url'] == manifest['source']['repo_url']
    assert facts['source']['commit_sha'] == manifest['source']['commit_sha']
    assert facts['source']['manifest_schema_version'] == manifest['schema_version']
    assert facts['source']['manifest_aggregate_sha256'] == manifest['reproducibility']['aggregate_sha256']
    assert facts['source']['coverage_schema_version'] == coverage['schema_version']
    assert facts['review']['review_status'] == 'reviewed'


def test_xaman_xrpl_transaction_source_inputs_are_manifest_bound() -> None:
    facts = _load_json(FACTS_PATH)
    manifest_files = _manifest_files()
    coverage_modules = _coverage_modules()

    source_inputs = facts['source_inputs']
    paths = {entry['path'] for entry in source_inputs}
    assert {
        'src/common/libs/ledger/factory/transaction.ts',
        'src/common/libs/ledger/factory/validation.ts',
        'src/common/libs/ledger/mixin/Sign.mixin.ts',
        'src/common/libs/ledger/mixin/Mutations.mixin.ts',
        'src/common/libs/ledger/transactions/common.ts',
        'src/common/libs/ledger/transactions/genuine/Payment/Payment.class.ts',
        'src/common/libs/ledger/transactions/genuine/Payment/Payment.validation.ts',
        'src/common/libs/ledger/transactions/genuine/TrustSet/TrustSet.class.ts',
        'src/common/libs/ledger/transactions/genuine/TrustSet/TrustSet.validation.ts',
        'src/common/libs/ledger/transactions/genuine/OfferCreate/OfferCreate.class.ts',
        'src/common/libs/ledger/transactions/genuine/OfferCreate/OfferCreate.validation.ts',
        'src/common/libs/ledger/transactions/genuine/SignerListSet/SignerListSet.class.ts',
        'src/common/libs/ledger/transactions/genuine/SignerListSet/SignerListSet.validation.ts',
        'src/common/libs/ledger/parser/common/amount.ts',
        'src/common/libs/ledger/parser/common/memo.ts',
        'src/common/libs/ledger/types/methods/submit.ts',
    } <= paths

    covered_categories = set()
    for source_input in source_inputs:
        manifest_entry = manifest_files[source_input['path']]
        assert source_input['sha256'] == manifest_entry['sha256']
        assert source_input['size_bytes'] == manifest_entry['size_bytes']
        assert source_input['categories']
        covered_categories.update(source_input['categories'])
        assert source_input['coverage_parse_status'] == 'content_unavailable'
        assert coverage_modules[source_input['path']]['parse_status'] == 'content_unavailable'

    assert REQUIRED_CATEGORIES <= covered_categories


def test_xaman_xrpl_transaction_model_has_required_reviewed_fact_categories() -> None:
    facts = _load_json(FACTS_PATH)
    modeled_facts = facts['modeled_facts']

    assert len(modeled_facts) >= 13
    assert {fact['id'] for fact in modeled_facts} >= REQUIRED_FACT_IDS
    assert {fact['category'] for fact in modeled_facts} >= REQUIRED_CATEGORIES
    assert all(fact['status'] == 'MODELED' for fact in modeled_facts)
    assert all(fact['summary'] and fact['normalized_fact'] for fact in modeled_facts)


def test_xaman_xrpl_transaction_common_signing_payment_and_multisign_facts() -> None:
    facts = _load_json(FACTS_PATH)
    by_id = {fact['id']: fact for fact in facts['modeled_facts']}

    common = by_id[
        'xaman-xrpl-transaction:fact:common-fields-require-account-sequence-last-ledger'
    ]['normalized_fact']
    assert {'TransactionType', 'Account', 'Sequence', 'LastLedgerSequence'} <= set(common['required_fields'])
    assert {'Fee', 'Memos', 'Signers', 'NetworkID'} <= set(common['optional_fields'])

    signing = by_id[
        'xaman-xrpl-transaction:fact:signing-requires-fee-sequence-network-and-supported-type'
    ]['normalized_fact']
    assert signing['requires_fee_before_signing'] is True
    assert signing['sets_sequence_when_missing'] is True
    assert signing['default_last_ledger_offset'] == 20
    assert signing['network_id_written_only_when_current_network_gt_1024'] is True
    assert signing['rejects_unsupported_transaction_type'] is True
    assert signing['rejects_already_signed_transaction'] is True

    payment = by_id[
        'xaman-xrpl-transaction:fact:payment-validation-blocks-zero-native-overspend-and-trustline-failures'
    ]['normalized_fact']
    assert payment['rejects_missing_or_zero_amount'] is True
    assert payment['checks_native_amount_against_available_balance'] is True
    assert payment['checks_destination_trustline_for_issued_currency'] is True
    assert payment['checks_issuer_freeze'] is True
    assert payment['checks_issuer_obligation_limit'] is True

    multisign = by_id[
        'xaman-xrpl-transaction:fact:signerlistset-models-quorum-and-signer-entries'
    ]['normalized_fact']
    assert multisign['fields'] == ['SignerQuorum', 'SignerEntries']
    assert multisign['signer_entries_codec'] == 'SignerEntries'
    assert multisign['validation_status'] == 'TODO_RESOLVES_WITHOUT_CHECKS'


def test_xaman_xrpl_transaction_amount_memo_mutation_and_submit_boundaries() -> None:
    facts = _load_json(FACTS_PATH)
    by_id = {fact['id']: fact for fact in facts['modeled_facts']}

    amount = by_id[
        'xaman-xrpl-transaction:fact:amount-parser-normalizes-drops-and-native-values'
    ]['normalized_fact']
    assert amount['drops_must_be_whole_units'] is True
    assert amount['native_to_drops_multiplier'] == 1000000
    assert amount['drops_to_native_divisor'] == 1000000

    memo = by_id['xaman-xrpl-transaction:fact:memo-parser-encodes-text-and-binary-memos']['normalized_fact']
    assert memo['binary_memo_min_hex_chars'] == 20
    assert memo['text_format'] == 'text/plain'
    assert memo['binary_format'] == 'application/x-binary'

    mutation = by_id[
        'xaman-xrpl-transaction:fact:mutations-remove-fee-from-balance-changes'
    ]['normalized_fact']
    assert mutation['deducts_fee_from_owner_native_balance_change'] is True
    assert mutation['removes_separate_fee_decrease_when_multiple_debits'] is True

    submit = by_id[
        'xaman-xrpl-transaction:fact:submit-boundary-is-signed-blob-preliminary-ledger-result'
    ]['normalized_fact']
    assert submit['request_command'] == 'submit'
    assert submit['requires_tx_blob'] is True
    assert {'accepted', 'applied', 'broadcast', 'kept', 'queued'} <= set(submit['preliminary_result_flags'])


def test_xaman_xrpl_transaction_gaps_are_explicit_and_blocking() -> None:
    facts = _load_json(FACTS_PATH)
    gaps = facts['not_modeled_gaps']

    assert {gap['id'] for gap in gaps} >= REQUIRED_GAP_IDS
    assert all(gap['status'] == 'NOT_MODELED' for gap in gaps)
    assert all(gap['required_evidence_to_model'] for gap in gaps)
    assert {
        'issued_currency_trustline',
        'transaction_type_dispatch',
        'fee_sequence_network',
        'broadcast_submit',
    } <= {gap['category'] for gap in gaps}

    boundary = facts['derived_security_boundary']
    assert any('XRPL consensus' in item for item in boundary['not_claimed'])
    assert any('LedgerService' in item for item in boundary['not_claimed'])
    assert any('complete amendment' in item.lower() for item in boundary['not_claimed'])


def test_xaman_xrpl_transaction_evidence_refs_are_reviewed_and_manifest_hashed() -> None:
    facts = _load_json(FACTS_PATH)
    manifest_files = _manifest_files()
    source_input_paths = {entry['path'] for entry in facts['source_inputs']}

    all_entries = facts['modeled_facts'] + facts['not_modeled_gaps']
    for entry in all_entries:
        assert entry['evidence'], entry['id']
        for evidence in entry['evidence']:
            assert evidence['review_status'] == 'reviewed'
            assert evidence['line_start'] >= 1
            assert evidence['line_end'] >= evidence['line_start']
            if evidence['kind'] == 'source_code':
                assert evidence['path'] in source_input_paths
                assert evidence['sha256'] == manifest_files[evidence['path']]['sha256']
            elif evidence['kind'] == 'source_manifest':
                assert evidence['path'] == 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
                assert evidence['sha256'] == facts['source']['manifest_aggregate_sha256']
            else:
                raise AssertionError(f'Unexpected evidence kind: {evidence}')


def test_xaman_xrpl_transaction_document_covers_artifact_and_gaps() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    facts = _load_json(FACTS_PATH)

    assert 'PORTAL-CXTP-066' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json' in doc
    assert facts['source']['commit_sha'] in doc
    assert 'NOT_MODELED' in doc
    for section in [
        'Common Transaction Fields',
        'Payment Semantics',
        'Issued Currency And Trustlines',
        'Multisign',
        'Network And Signing Bounds',
        'Broadcast Boundary',
    ]:
        assert section in doc
