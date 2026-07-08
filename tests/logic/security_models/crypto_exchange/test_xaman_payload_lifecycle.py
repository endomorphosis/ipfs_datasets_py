import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
FACTS_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'payload-lifecycle-facts.json'
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
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_payload_lifecycle_model.md'


REQUIRED_CATEGORIES = {
    'payload_creation',
    'qr_intake',
    'deep_link_intake',
    'push_intake',
    'event_list_intake',
    'review_ui',
    'approval',
    'rejection',
    'expiration',
    'replay_control',
    'network_binding',
    'broadcast_boundary',
}

REQUIRED_FACT_IDS = {
    'xaman-payload-lifecycle:fact:payload-build-creates-local-sign-request',
    'xaman-payload-lifecycle:fact:remote-payload-fetch-verifies-request-json-digest',
    'xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads',
    'xaman-payload-lifecycle:fact:qr-payload-reference-intake-fetches-and-routes-to-review',
    'xaman-payload-lifecycle:fact:deep-link-payload-reference-intake-fetches-and-routes-to-review',
    'xaman-payload-lifecycle:fact:event-list-loads-pending-payloads-and-opens-review',
    'xaman-payload-lifecycle:fact:review-preflight-binds-forced-network-and-signer',
    'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
    'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
    'xaman-payload-lifecycle:fact:rejection-patches-backend-for-user-or-app-decline',
    'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
    'xaman-payload-lifecycle:fact:signed-payload-is-patched-before-optional-ledger-broadcast',
    'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign',
    'xaman-payload-lifecycle:fact:ledger-submit-has-local-single-submit-and-abort-guards',
    'xaman-payload-lifecycle:fact:dispatch-result-is-patched-after-ledger-submit',
}

REQUIRED_GAP_IDS = {
    'xaman-payload-lifecycle:gap:backend-payload-creation-auth-and-single-use',
    'xaman-payload-lifecycle:gap:string-decoder-and-native-intake-integrity',
    'xaman-payload-lifecycle:gap:ledger-consensus-and-node-honesty',
    'xaman-payload-lifecycle:gap:deployed-runtime-equivalence',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _manifest_files() -> dict[str, dict[str, Any]]:
    manifest = _load_json(MANIFEST_PATH)
    return {entry['path']: entry for entry in manifest['files']}


def _coverage_modules() -> dict[str, dict[str, Any]]:
    coverage = _load_json(COVERAGE_PATH)
    return {entry['path']: entry for entry in coverage['security_relevant_modules']}


def test_xaman_payload_lifecycle_schema_and_source_pin() -> None:
    facts = _load_json(FACTS_PATH)
    manifest = _load_json(MANIFEST_PATH)
    coverage = _load_json(COVERAGE_PATH)

    assert facts['schema_version'] == 'xaman-payload-lifecycle-facts/v1'
    assert facts['task_id'] == 'PORTAL-CXTP-042'
    assert facts['corpus'] == 'xaman-app'
    assert facts['source']['repo_url'] == manifest['source']['repo_url']
    assert facts['source']['commit_sha'] == manifest['source']['commit_sha']
    assert facts['source']['manifest_schema_version'] == manifest['schema_version']
    assert facts['source']['manifest_aggregate_sha256'] == manifest['reproducibility']['aggregate_sha256']
    assert facts['source']['coverage_schema_version'] == coverage['schema_version']
    assert facts['review']['review_status'] == 'reviewed'


def test_xaman_payload_lifecycle_source_inputs_are_manifest_bound() -> None:
    facts = _load_json(FACTS_PATH)
    manifest_files = _manifest_files()
    coverage_modules = _coverage_modules()

    source_inputs = facts['source_inputs']
    paths = {entry['path'] for entry in source_inputs}
    assert {
        'src/common/libs/payload/object.ts',
        'src/common/libs/payload/types.ts',
        'src/common/libs/payload/digest/serialize.ts',
        'src/screens/Modal/Scan/ScanModal.tsx',
        'src/services/LinkingService.ts',
        'src/services/PushNotificationsService.ts',
        'src/services/BackendService.ts',
        'src/screens/Events/EventsView.tsx',
        'src/components/Modules/EventsList/EventListItems/Request.tsx',
        'src/screens/Modal/ReviewTransaction/ReviewTransactionModal.tsx',
        'src/screens/Modal/ReviewTransaction/Steps/Preflight/PreflightStep.tsx',
        'src/screens/Modal/ReviewTransaction/Steps/Review/ReviewStep.tsx',
        'src/common/libs/ledger/mixin/Sign.mixin.ts',
        'src/common/libs/ledger/types/methods/submit.ts',
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


def test_xaman_payload_lifecycle_model_has_required_reviewed_fact_categories() -> None:
    facts = _load_json(FACTS_PATH)
    modeled_facts = facts['modeled_facts']

    assert len(modeled_facts) >= 15
    assert {fact['id'] for fact in modeled_facts} >= REQUIRED_FACT_IDS
    assert {fact['category'] for fact in modeled_facts} >= REQUIRED_CATEGORIES
    assert all(fact['status'] == 'MODELED' for fact in modeled_facts)
    assert all(fact['summary'] and fact['normalized_fact'] for fact in modeled_facts)

    states = facts['lifecycle_model']['states']
    assert states.index('fetched_verified') < states.index('review_displayed')
    assert states.index('approved_revalidated') < states.index('signed')
    assert 'expired_or_resolved_blocked' in facts['lifecycle_model']['terminal_states']
    assert 'submitted' not in facts['lifecycle_model']['non_broadcast_path']


def test_xaman_payload_lifecycle_replay_expiration_and_rejection_controls() -> None:
    facts = _load_json(FACTS_PATH)
    by_id = {fact['id']: fact for fact in facts['modeled_facts']}

    digest = by_id['xaman-payload-lifecycle:fact:remote-payload-fetch-verifies-request-json-digest']
    assert digest['normalized_fact']['rejects_digest_mismatch'] is True
    assert digest['normalized_fact']['digest_algorithm_header'] == 'DigestSerializeWithSHA1'

    expiration = by_id['xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads']
    assert expiration['normalized_fact']['rejects_resolved_at'] is True
    assert expiration['normalized_fact']['rejects_meta_expired'] is True

    approval = by_id['xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing']
    assert approval['normalized_fact']['revalidates_remote_payload'] is True
    assert approval['normalized_fact']['stops_on_validation_error'] is True

    submit_guard = by_id['xaman-payload-lifecycle:fact:ledger-submit-has-local-single-submit-and-abort-guards']
    assert submit_guard['normalized_fact']['requires_signed_blob'] is True
    assert submit_guard['normalized_fact']['rejects_already_submitted'] is True
    assert submit_guard['normalized_fact']['sets_is_submitted_before_network_call'] is True

    rejection = by_id['xaman-payload-lifecycle:fact:rejection-patches-backend-for-user-or-app-decline']
    assert set(rejection['normalized_fact']['reject_initiator_values']) == {'USER', 'APP'}
    assert rejection['normalized_fact']['origin_included'] is True


def test_xaman_payload_lifecycle_network_and_broadcast_boundaries() -> None:
    facts = _load_json(FACTS_PATH)
    by_id = {fact['id']: fact for fact in facts['modeled_facts']}

    network = by_id['xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing']
    assert network['normalized_fact']['template_network_mismatch_blocked'] is True
    assert network['normalized_fact']['force_network_preflight'] is True
    assert network['normalized_fact']['network_id_auto_populated_when_network_id_gt_1024'] is True
    assert network['normalized_fact']['unsupported_transaction_type_rejected'] is True

    signed_patch = by_id[
        'xaman-payload-lifecycle:fact:signed-payload-is-patched-before-optional-ledger-broadcast'
    ]['normalized_fact']
    assert signed_patch['signed_patch_before_submit'] is True
    assert {
        'signed_blob',
        'tx_id',
        'signmethod',
        'signpubkey',
        'environment.nodeuri',
        'environment.nodetype',
    } <= set(signed_patch['patched_fields'])

    broadcast = by_id[
        'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign'
    ]['normalized_fact']
    assert broadcast['submit_required'] == 'meta.submit'
    assert broadcast['pseudo_submits'] is False
    assert broadcast['multisign_submits'] is False

    submit_boundary = by_id['xaman-payload-lifecycle:fact:submit-request-type-boundary-is-xrpl-submit']
    assert submit_boundary['normalized_fact']['ledger_command'] == 'submit'
    assert submit_boundary['normalized_fact']['response_includes_broadcast'] is True


def test_xaman_payload_lifecycle_evidence_refs_are_reviewed_and_manifest_hashed() -> None:
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


def test_xaman_payload_lifecycle_marks_unsupported_boundaries_not_modeled() -> None:
    facts = _load_json(FACTS_PATH)
    gaps = facts['not_modeled_gaps']

    assert {gap['id'] for gap in gaps} >= REQUIRED_GAP_IDS
    assert all(gap['status'] == 'NOT_MODELED' for gap in gaps)
    assert all(gap['required_evidence_to_model'] for gap in gaps)
    assert {
        'replay_control',
        'qr_intake',
        'broadcast_boundary',
        'review_ui',
    } <= {gap['category'] for gap in gaps}

    boundary = facts['derived_security_boundary']
    assert any('Backend payload API' in item for item in boundary['not_claimed'])
    assert any('Native camera' in item for item in boundary['not_claimed'])
    assert any('Ledger consensus' in item for item in boundary['not_claimed'])
    assert any('Deployed mobile binary' in item for item in boundary['not_claimed'])


def test_xaman_payload_lifecycle_document_covers_artifact_and_gaps() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    facts = _load_json(FACTS_PATH)

    assert 'PORTAL-CXTP-042' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json' in doc
    assert facts['source']['commit_sha'] in doc
    assert 'NOT_MODELED' in doc
    for section in [
        'Payload Creation',
        'QR And Deep-Link Intake',
        'Review UI',
        'Approval And Signing',
        'Rejection And Expiration',
        'Replay Controls',
        'Network Binding',
        'Broadcast Boundaries',
    ]:
        assert section in doc
