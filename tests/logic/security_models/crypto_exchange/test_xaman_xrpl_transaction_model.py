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
    'account',
    'destination',
    'amount',
    'fee',
    'sequence',
    'network',
    'memo',
    'issued_currency',
    'trustline',
    'multisign',
    'transaction_type',
}

REQUIRED_FACT_IDS = {
    'xaman-xrpl-transaction:fact:account-field-requires-valid-classic-address',
    'xaman-xrpl-transaction:fact:signing-account-defaults-to-selected-account-unless-multisign-or-import',
    'xaman-xrpl-transaction:fact:payment-destination-is-a-required-accountid-field',
    'xaman-xrpl-transaction:fact:amount-field-represents-native-drops-or-issued-currency-object',
    'xaman-xrpl-transaction:fact:payment-amount-must-be-present-and-nonzero-unless-paths-set',
    'xaman-xrpl-transaction:fact:amount-parser-enforces-whole-drop-integers-and-numeric-strings',
    'xaman-xrpl-transaction:fact:fee-is-an-optional-amount-typed-common-field',
    'xaman-xrpl-transaction:fact:signing-requires-fee-to-be-explicitly-set-before-prepare-completes',
    'xaman-xrpl-transaction:fact:sequence-is-a-required-uint32-common-field',
    'xaman-xrpl-transaction:fact:signing-auto-fills-missing-sequence-from-live-account-sequence',
    'xaman-xrpl-transaction:fact:networkid-is-an-optional-uint32-common-field',
    'xaman-xrpl-transaction:fact:network-id-is-auto-populated-for-non-legacy-networks-above-1024',
    'xaman-xrpl-transaction:fact:signing-rejects-transaction-types-unsupported-by-connected-network-definitions',
    'xaman-xrpl-transaction:fact:memos-field-is-an-starray-of-memo-entries',
    'xaman-xrpl-transaction:fact:memo-encoder-classifies-hex-blob-vs-plain-text-before-hex-encoding',
    'xaman-xrpl-transaction:fact:memo-decoder-reverses-format-specific-encodings-for-display',
    'xaman-xrpl-transaction:fact:issued-currency-amount-requires-currency-and-issuer-when-non-native',
    'xaman-xrpl-transaction:fact:issue-type-pairs-currency-and-issuer-for-trustline-lookups',
    'xaman-xrpl-transaction:fact:trustset-transaction-declares-limitamount-quality-in-and-quality-out',
    'xaman-xrpl-transaction:fact:payment-requires-recipient-trustline-for-non-native-non-issuer-delivery',
    'xaman-xrpl-transaction:fact:payment-checks-sender-trustline-balance-freeze-and-limit-before-sending-issued-currency',
    'xaman-xrpl-transaction:fact:trustline-lookup-uses-ripple-state-ledger-entry-with-reserve-flag-check',
    'xaman-xrpl-transaction:fact:signerlistset-declares-signer-quorum-and-weighted-signer-entries',
    'xaman-xrpl-transaction:fact:multisign-flag-is-derived-from-payload-meta-multisign',
    'xaman-xrpl-transaction:fact:multisign-transactions-skip-account-autofill-sequence-fee-prep-and-client-validation',
    'xaman-xrpl-transaction:fact:multisign-transactions-are-excluded-from-automatic-ledger-submission',
    'xaman-xrpl-transaction:fact:submit-multisigned-request-requires-signer-weights-meeting-signerlist-quorum',
    'xaman-xrpl-transaction:fact:transactiontype-is-a-required-common-field-set-by-each-transaction-class',
    'xaman-xrpl-transaction:fact:unknown-transaction-types-fall-back-to-fallback-transaction-class',
    'xaman-xrpl-transaction:fact:validation-dispatch-requires-a-matching-typevalidation-export-or-throws',
}

REQUIRED_GAP_IDS = {
    'xaman-xrpl-transaction:gap:trustset-and-signerlistset-client-validation-not-implemented',
    'xaman-xrpl-transaction:gap:xrpl-server-side-transaction-rule-enforcement-not-modeled',
    'xaman-xrpl-transaction:gap:external-multisign-signature-collection-not-modeled',
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
    assert REQUIRED_CATEGORIES <= set(facts['review']['review_scope'])


def test_xaman_xrpl_transaction_source_inputs_are_manifest_bound() -> None:
    facts = _load_json(FACTS_PATH)
    manifest_files = _manifest_files()
    coverage_modules = _coverage_modules()

    source_inputs = facts['source_inputs']
    paths = {entry['path'] for entry in source_inputs}
    assert {
        'src/common/libs/ledger/transactions/common.ts',
        'src/common/libs/ledger/transactions/genuine/base.ts',
        'src/common/libs/ledger/transactions/genuine/Payment/Payment.class.ts',
        'src/common/libs/ledger/transactions/genuine/Payment/Payment.validation.ts',
        'src/common/libs/ledger/transactions/genuine/TrustSet/TrustSet.class.ts',
        'src/common/libs/ledger/transactions/genuine/TrustSet/TrustSet.validation.ts',
        'src/common/libs/ledger/transactions/genuine/SignerListSet/SignerListSet.class.ts',
        'src/common/libs/ledger/transactions/genuine/SignerListSet/SignerListSet.validation.ts',
        'src/common/libs/ledger/mixin/Sign.mixin.ts',
        'src/common/libs/ledger/parser/common/amount.ts',
        'src/common/libs/ledger/parser/common/memo.ts',
        'src/common/libs/ledger/parser/fields/Issue.ts',
        'src/common/libs/ledger/parser/fields/Amount.ts',
        'src/common/libs/ledger/parser/fields/AccountID.ts',
        'src/common/libs/ledger/parser/fields/UInt32.ts',
        'src/common/libs/ledger/parser/fields/TransactionType.ts',
        'src/common/libs/ledger/parser/types.ts',
        'src/common/libs/ledger/factory/validation.ts',
        'src/common/libs/ledger/factory/transaction.ts',
        'src/common/libs/ledger/types/methods/submitMultisigned.ts',
        'src/common/libs/payload/object.ts',
        'src/screens/Modal/ReviewTransaction/ReviewTransactionModal.tsx',
        'src/services/NetworkService.ts',
        'src/services/LedgerService.ts',
    } <= paths

    covered_categories = set()
    for source_input in source_inputs:
        manifest_entry = manifest_files[source_input['path']]
        assert source_input['sha256'] == manifest_entry['sha256']
        assert source_input['size_bytes'] == manifest_entry['size_bytes']
        assert source_input['categories']
        covered_categories.update(source_input['categories'])

        if source_input['coverage_parse_status'] == 'content_unavailable':
            assert coverage_modules[source_input['path']]['parse_status'] == 'content_unavailable'
        elif source_input['coverage_parse_status'] == 'not_in_xaman_source_coverage_roots':
            assert source_input['path'] not in coverage_modules
        else:
            raise AssertionError(f'Unexpected coverage status: {source_input}')

    assert REQUIRED_CATEGORIES <= covered_categories


def test_xaman_xrpl_transaction_model_has_required_reviewed_fact_categories() -> None:
    facts = _load_json(FACTS_PATH)
    modeled_facts = facts['modeled_facts']

    assert len(modeled_facts) >= 25
    assert {fact['id'] for fact in modeled_facts} >= REQUIRED_FACT_IDS
    assert {fact['category'] for fact in modeled_facts} >= REQUIRED_CATEGORIES
    assert all(fact['status'] == 'MODELED' for fact in modeled_facts)
    assert all(fact['summary'] and fact['normalized_fact'] for fact in modeled_facts)


def test_xaman_xrpl_transaction_field_model_covers_common_and_type_specific_fields() -> None:
    facts = _load_json(FACTS_PATH)
    field_model = facts['field_model']

    common_fields = field_model['common_fields']
    assert {'hash', 'TransactionType', 'Account', 'Sequence', 'LastLedgerSequence'} <= set(common_fields['required'])
    assert {'Fee', 'Memos', 'Signers', 'NetworkID', 'TicketSequence'} <= set(common_fields['optional'])

    payment_fields = field_model['payment_fields']
    assert set(payment_fields['required']) == {'Amount', 'Destination'}
    assert {'SendMax', 'DeliverMin', 'Paths'} <= set(payment_fields['optional'])

    trustset_fields = field_model['trustset_fields']
    assert trustset_fields['required'] == ['LimitAmount']
    assert {'QualityIn', 'QualityOut'} <= set(trustset_fields['optional'])

    signerlistset_fields = field_model['signerlistset_fields']
    assert {'SignerQuorum', 'SignerEntries'} <= set(signerlistset_fields['optional'])

    amount_shapes = field_model['amount_shapes']
    assert 'native' in amount_shapes and 'issued_currency' in amount_shapes
    assert set(amount_shapes['issued_currency']['fields']) == {'currency', 'value', 'issuer'}

    network_binding = field_model['network_binding']
    assert network_binding['legacy_network_id_threshold'] == 1024
    assert network_binding['network_id_populated_when_gt_threshold'] is True

    multisign_binding = field_model['multisign_binding']
    assert multisign_binding['flag_source'] == 'payload.meta.multisign'
    assert multisign_binding['excluded_from_should_submit'] is True
    assert multisign_binding['ledger_command'] == 'submit_multisigned'


def test_xaman_xrpl_transaction_fee_sequence_and_network_signing_preconditions() -> None:
    facts = _load_json(FACTS_PATH)
    by_id = {fact['id']: fact for fact in facts['modeled_facts']}

    fee_precond = by_id['xaman-xrpl-transaction:fact:signing-requires-fee-to-be-explicitly-set-before-prepare-completes']
    assert fee_precond['normalized_fact']['throws_when_fee_undefined'] is True

    sequence_autofill = by_id['xaman-xrpl-transaction:fact:signing-auto-fills-missing-sequence-from-live-account-sequence']
    assert sequence_autofill['normalized_fact']['autofill_source'] == 'LedgerService.getAccountSequence'
    assert sequence_autofill['normalized_fact']['throws_on_fetch_failure'] is True

    network_autofill = by_id['xaman-xrpl-transaction:fact:network-id-is-auto-populated-for-non-legacy-networks-above-1024']
    assert network_autofill['normalized_fact']['legacy_network_threshold'] == 1024
    assert network_autofill['normalized_fact']['sets_network_id_when_gt_threshold'] is True

    network_reject = by_id[
        'xaman-xrpl-transaction:fact:signing-rejects-transaction-types-unsupported-by-connected-network-definitions'
    ]
    assert network_reject['normalized_fact']['rejects_unsupported_transaction_type'] is True
    assert network_reject['normalized_fact']['checked_against'] == 'NetworkService.getNetworkDefinitions().transactionNames'


def test_xaman_xrpl_transaction_issued_currency_and_trustline_constraints() -> None:
    facts = _load_json(FACTS_PATH)
    by_id = {fact['id']: fact for fact in facts['modeled_facts']}

    issued_currency = by_id['xaman-xrpl-transaction:fact:issued-currency-amount-requires-currency-and-issuer-when-non-native']
    assert issued_currency['normalized_fact']['requires_issuer_for_non_native'] is True
    assert set(issued_currency['normalized_fact']['amount_type_fields']) == {'value', 'currency', 'issuer'}

    recipient_trustline = by_id[
        'xaman-xrpl-transaction:fact:payment-requires-recipient-trustline-for-non-native-non-issuer-delivery'
    ]
    assert recipient_trustline['normalized_fact']['requires_destination_trustline'] is True
    assert recipient_trustline['normalized_fact']['rejects_zero_limit_and_zero_balance_trustline'] is True

    sender_trustline = by_id[
        'xaman-xrpl-transaction:fact:payment-checks-sender-trustline-balance-freeze-and-limit-before-sending-issued-currency'
    ]
    assert 'not_frozen_by_issuer' in sender_trustline['normalized_fact']['non_issuer_sender_checks']
    assert 'obligation_within_limit_peer' in sender_trustline['normalized_fact']['issuer_sender_checks']

    trustline_lookup = by_id['xaman-xrpl-transaction:fact:trustline-lookup-uses-ripple-state-ledger-entry-with-reserve-flag-check']
    assert trustline_lookup['normalized_fact']['ledger_entry_type'] == 'ripple_state'
    assert trustline_lookup['normalized_fact']['requires_reserve_flag_set'] is True


def test_xaman_xrpl_transaction_multisign_and_transaction_type_dispatch() -> None:
    facts = _load_json(FACTS_PATH)
    by_id = {fact['id']: fact for fact in facts['modeled_facts']}

    multisign_flag = by_id['xaman-xrpl-transaction:fact:multisign-flag-is-derived-from-payload-meta-multisign']
    assert multisign_flag['normalized_fact']['source_field'] == 'meta.multisign'

    multisign_skip = by_id[
        'xaman-xrpl-transaction:fact:multisign-transactions-skip-account-autofill-sequence-fee-prep-and-client-validation'
    ]
    assert multisign_skip['normalized_fact']['skips_account_autofill'] is True
    assert multisign_skip['normalized_fact']['skips_client_validation'] is True
    assert multisign_skip['normalized_fact']['skips_prepare_fee_sequence_population'] is True

    multisign_submit = by_id['xaman-xrpl-transaction:fact:multisign-transactions-are-excluded-from-automatic-ledger-submission']
    assert multisign_submit['normalized_fact']['should_submit_excludes_multisign'] is True

    quorum = by_id['xaman-xrpl-transaction:fact:submit-multisigned-request-requires-signer-weights-meeting-signerlist-quorum']
    assert quorum['normalized_fact']['command'] == 'submit_multisigned'
    assert quorum['normalized_fact']['quorum_rule'] == 'sum_of_signer_weights_gte_signerlist_quorum'

    fallback = by_id['xaman-xrpl-transaction:fact:unknown-transaction-types-fall-back-to-fallback-transaction-class']
    assert fallback['normalized_fact']['unregistered_type_uses_fallback'] is True
    assert fallback['normalized_fact']['fallback_class'] == 'FallbackTransaction'

    validation_dispatch = by_id['xaman-xrpl-transaction:fact:validation-dispatch-requires-a-matching-typevalidation-export-or-throws']
    assert validation_dispatch['normalized_fact']['throws_when_validation_missing'] is True


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


def test_xaman_xrpl_transaction_marks_unsupported_boundaries_not_modeled() -> None:
    facts = _load_json(FACTS_PATH)
    gaps = facts['not_modeled_gaps']

    assert {gap['id'] for gap in gaps} >= REQUIRED_GAP_IDS
    assert all(gap['status'] == 'NOT_MODELED' for gap in gaps)
    assert all(gap['required_evidence_to_model'] for gap in gaps)
    assert {
        'trustline',
        'transaction_type',
        'multisign',
    } <= {gap['category'] for gap in gaps}

    boundary = facts['derived_security_boundary']
    assert any('TrustSet and SignerListSet' in item for item in boundary['not_claimed'])
    assert any('rippled' in item for item in boundary['not_claimed'])
    assert any('multisign signature collection' in item for item in boundary['not_claimed'])
    assert any('Deployed mobile binary' in item for item in boundary['not_claimed'])


def test_xaman_xrpl_transaction_document_covers_artifact_and_gaps() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    facts = _load_json(FACTS_PATH)

    assert 'PORTAL-CXTP-066' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json' in doc
    assert facts['source']['commit_sha'] in doc
    assert 'NOT_MODELED' in doc
    for section in [
        'Account',
        'Destination',
        'Amount',
        'Fee',
        'Sequence',
        'Network',
        'Memo',
        'Issued Currency',
        'Trustline',
        'Multisign',
        'Transaction Type',
    ]:
        assert section in doc
