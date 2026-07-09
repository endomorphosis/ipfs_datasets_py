from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (
    calculate_artifact_cid,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_tla_workflow import (
    APALACHE_REPORT_PATH,
    MODULE_NAME,
    REQUIRED_OPERATORS,
    REQUIRED_TRANSITION_CATEGORIES,
    SCHEMA_VERSION,
    TASK_ID,
    TLA_ARTIFACT_PATH,
    XAMAN_SIGNING_TLA,
    build_xaman_tla_workflow_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
LIFECYCLE_FACTS_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'
TLA_PATH = REPO_ROOT / TLA_ARTIFACT_PATH
REPORT_PATH = REPO_ROOT / APALACHE_REPORT_PATH
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_tla_workflow.md'

REQUIRED_FACT_IDS = {
    'xaman-payload-lifecycle:fact:remote-payload-fetch-verifies-request-json-digest',
    'xaman-payload-lifecycle:fact:review-preflight-binds-forced-network-and-signer',
    'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
    'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
    'xaman-payload-lifecycle:fact:approval-enters-vault-signing-boundary',
    'xaman-payload-lifecycle:fact:rejection-patches-backend-for-user-or-app-decline',
    'xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads',
    'xaman-payload-lifecycle:fact:ledger-submit-has-local-single-submit-and-abort-guards',
    'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
    'xaman-payload-lifecycle:fact:signed-payload-is-patched-before-optional-ledger-broadcast',
    'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign',
    'xaman-payload-lifecycle:fact:dispatch-result-is-patched-after-ledger-submit',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != 'artifact_cid'
    }


def _expected_report() -> dict[str, Any]:
    return build_xaman_tla_workflow_report(
        model_payload=_load_json(MODEL_PATH),
        model_cid=MODEL_CID_PATH.read_text(encoding='utf-8').strip(),
        lifecycle_facts=_load_json(LIFECYCLE_FACTS_PATH),
        tla_source=TLA_PATH.read_text(encoding='utf-8').rstrip('\n'),
        apalache_executable=None,
        apalache_version=None,
    )


def test_xaman_tla_report_is_generated_from_current_inputs() -> None:
    checked_in = _load_json(REPORT_PATH)
    expected = _expected_report()

    assert checked_in == expected
    assert checked_in['schema_version'] == SCHEMA_VERSION
    assert checked_in['task_id'] == TASK_ID
    assert checked_in['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert checked_in['artifact_cid'] == calculate_artifact_cid(
        _without_artifact_cid(checked_in)
    )
    assert checked_in['tla_module']['artifact_cid'] == calculate_artifact_cid(
        {
            'module_name': MODULE_NAME,
            'source': TLA_PATH.read_text(encoding='utf-8').rstrip('\n'),
        }
    )


def test_xaman_tla_module_declares_required_workflow_actions_and_properties() -> None:
    tla = TLA_PATH.read_text(encoding='utf-8')

    assert tla.rstrip('\n') == XAMAN_SIGNING_TLA
    assert tla.startswith(f'---- MODULE {MODULE_NAME} ----')
    assert 'TODO' not in tla
    assert 'Spec == Init /\\ [][Next]_Vars' in tla

    for operator in REQUIRED_OPERATORS:
        assert re.search(rf'^{re.escape(operator)}\s*==', tla, re.MULTILINE), operator

    for action in [
        'Fetch',
        'FetchWrongNetwork',
        'Review',
        'Approve',
        'Revalidate',
        'Sign',
        'Reject',
        'Expire',
        'ReplayAttempt',
        'NetworkMismatchBlock',
        'PatchSigned',
        'PatchSignedNoSubmit',
        'Broadcast',
        'DispatchPatch',
        'ResultDisplay',
    ]:
        assert re.search(rf'^\s*\\/ {re.escape(action)}$', tla, re.MULTILINE), action

    assert 'state = "FetchedVerified"' in tla
    assert 'state = "ReviewDisplayed"' in tla
    assert 'state = "Revalidated"' in tla
    assert 'state = "ReplayBlocked"' in tla
    assert 'state\' = "NetworkMismatchBlocked"' in tla


def test_xaman_tla_report_covers_required_transition_categories_and_evidence() -> None:
    report = _load_json(REPORT_PATH)
    lifecycle_facts = _load_json(LIFECYCLE_FACTS_PATH)
    fact_ids = {fact['id'] for fact in lifecycle_facts['modeled_facts']}
    properties = report['properties']

    assert report['tla_module']['transition_categories'] == list(REQUIRED_TRANSITION_CATEGORIES)
    assert {entry['category'] for entry in properties} == set(REQUIRED_TRANSITION_CATEGORIES)
    assert {fact_id for entry in properties for fact_id in entry['evidence_fact_ids']} >= (
        REQUIRED_FACT_IDS
    )
    assert report['missing_evidence_fact_ids'] == []
    assert report['summary']['missing_evidence_count'] == 0

    for entry in properties:
        assert entry['modeled'] is True
        assert entry['operator'] in report['tla_module']['required_operators']
        assert entry['transition_actions']
        assert entry['claim_ids'], entry['category']
        assert entry['assumption_ids'], entry['category']
        assert set(entry['evidence_fact_ids']) <= fact_ids
        assert entry['description']


def test_xaman_tla_report_marks_apalache_absence_as_solver_blocker() -> None:
    report = _load_json(REPORT_PATH)
    apalache = report['apalache']
    summary = report['summary']

    assert apalache == {
        'available': False,
        'blocker': {
            'kind': 'missing_solver',
            'message': 'Apalache executable was not available when this workflow report was generated; temporal checks are solver-blocked and must not be accepted as proved.',
            'required_action': 'Install Apalache and rerun the XamanSigning.tla checks before promoting any property to PROVED.',
            'solver': 'apalache',
        },
        'executable': None,
        'solver': 'apalache',
        'status': 'BLOCKED',
        'version': None,
    }
    assert summary == {
        'apalache_available': False,
        'blocked_property_count': 10,
        'checked_property_count': 0,
        'missing_evidence_count': 0,
        'modeled_property_count': 10,
        'property_count': 10,
        'release_ready': False,
    }

    for entry in report['properties']:
        assert entry['classification'] == 'BLOCKED'
        assert entry['solver_status'] == 'BLOCKED'
        assert entry['solver_blocker'] == apalache['blocker']
        assert entry['apalache_command'][0] == 'apalache-mc'


def test_xaman_tla_properties_encode_specific_acceptance_cases() -> None:
    properties = {
        entry['category']: entry
        for entry in _load_json(REPORT_PATH)['properties']
    }

    assert properties['fetch']['operator'] == 'FetchSafety'
    assert set(properties['fetch']['transition_actions']) == {'Fetch', 'FetchWrongNetwork'}

    assert properties['review']['operator'] == 'ReviewRequiresVerifiedFetch'
    assert properties['approval']['operator'] == 'ApprovalRequiresReview'
    assert properties['revalidation']['operator'] == 'RevalidationPrecedesSigning'

    signing = properties['signing']
    assert signing['operator'] == 'SigningRequiresFreshNetworkBoundPayload'
    assert 'xaman-security:claim:authentication-gates-vault-and-signing' in signing['claim_ids']
    assert 'xaman-security:assumption:authentication-overlay-gates-vault-signing' in (
        signing['assumption_ids']
    )

    assert properties['rejection']['transition_actions'] == ['Reject']
    assert properties['expiration']['transition_actions'] == ['Expire']
    assert properties['replay']['transition_actions'] == ['ReplayAttempt']

    network = properties['network_binding']
    assert network['operator'] == 'NetworkBindingSafety'
    assert {'NetworkMismatchBlock', 'Review', 'Sign', 'Broadcast'} <= set(
        network['transition_actions']
    )
    assert 'xaman-security:claim:network-binding-prevents-cross-network-signing' in (
        network['claim_ids']
    )

    broadcast = properties['broadcast']
    assert broadcast['operator'] == 'BroadcastAfterSignedPatch'
    assert {'PatchSigned', 'PatchSignedNoSubmit', 'Broadcast', 'DispatchPatch'} <= set(
        broadcast['transition_actions']
    )
    assert 'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign' in (
        broadcast['evidence_fact_ids']
    )


def test_xaman_tla_workflow_doc_links_artifacts_and_blocker_policy() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    normalized_doc = ' '.join(doc.split())

    assert 'PORTAL-CXTP-071' in doc
    assert TLA_ARTIFACT_PATH in doc
    assert APALACHE_REPORT_PATH in doc
    assert 'generate_xaman_tla_workflow.py' in doc
    assert 'test_xaman_tla_workflow.py' in doc
    assert 'Apalache is not available' in doc
    assert (
        'must not promote' in normalized_doc
        or 'must not be accepted as proved' in normalized_doc
    )
