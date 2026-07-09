"""TLA+/Apalache workflow artifacts for Xaman signing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (
    calculate_artifact_cid,
)


SCHEMA_VERSION = 'xaman-tla-workflow-report/v1'
TASK_ID = 'PORTAL-CXTP-071'
MODULE_NAME = 'XamanSigning'
TLA_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla'
APALACHE_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json'

REQUIRED_TRANSITION_CATEGORIES = (
    'fetch',
    'review',
    'approval',
    'revalidation',
    'signing',
    'rejection',
    'expiration',
    'replay',
    'network_binding',
    'broadcast',
)

REQUIRED_OPERATORS = (
    'Init',
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
    'Next',
    'Spec',
    'TypeOK',
    'FetchSafety',
    'ReviewRequiresVerifiedFetch',
    'ApprovalRequiresReview',
    'RevalidationPrecedesSigning',
    'SigningRequiresFreshNetworkBoundPayload',
    'RejectionIsTerminalAndUnsigned',
    'ExpirationBlocksSigningAndBroadcast',
    'ReplayIsBlocked',
    'NetworkBindingSafety',
    'BroadcastAfterSignedPatch',
)

XAMAN_SIGNING_TLA = r'''---- MODULE XamanSigning ----
EXTENDS Naturals

\* PORTAL-CXTP-071: client-side Xaman payload signing workflow.
\* The model is intentionally finite so Apalache can bounded-check the
\* source-backed fetch, review, approval, revalidation, signing, rejection,
\* expiration, replay, network-binding, and broadcast transitions.

VARIABLES
  state,
  payloadFetched,
  digestVerified,
  reviewShown,
  userApproved,
  revalidated,
  signed,
  rejected,
  expired,
  replayAttempt,
  networkBound,
  broadcasted,
  signedPatchSent,
  submitRequested,
  dispatchPatched,
  uuidConsumed,
  origin

States ==
  {"ReferencedRemote", "FetchedVerified", "ReviewDisplayed", "Approved",
   "Revalidated", "Signed", "PatchedSigned", "Submitted",
   "DispatchPatched", "ResultDisplayed", "Rejected", "Expired",
   "ReplayBlocked", "NetworkMismatchBlocked"}

Origins == {"QR", "DEEP_LINK", "PUSH_NOTIFICATION", "EVENT_LIST"}

Vars ==
  << state, payloadFetched, digestVerified, reviewShown, userApproved,
     revalidated, signed, rejected, expired, replayAttempt, networkBound,
     broadcasted, signedPatchSent, submitRequested, dispatchPatched,
     uuidConsumed, origin >>

Init ==
  /\ state = "ReferencedRemote"
  /\ payloadFetched = FALSE
  /\ digestVerified = FALSE
  /\ reviewShown = FALSE
  /\ userApproved = FALSE
  /\ revalidated = FALSE
  /\ signed = FALSE
  /\ rejected = FALSE
  /\ expired = FALSE
  /\ replayAttempt = FALSE
  /\ networkBound = FALSE
  /\ broadcasted = FALSE
  /\ signedPatchSent = FALSE
  /\ submitRequested = FALSE
  /\ dispatchPatched = FALSE
  /\ uuidConsumed = FALSE
  /\ origin \in Origins

Fetch ==
  /\ state = "ReferencedRemote"
  /\ ~payloadFetched
  /\ ~expired
  /\ payloadFetched' = TRUE
  /\ digestVerified' = TRUE
  /\ networkBound' = TRUE
  /\ state' = "FetchedVerified"
  /\ UNCHANGED <<reviewShown, userApproved, revalidated, signed, rejected,
                 expired, replayAttempt, broadcasted, signedPatchSent,
                 submitRequested, dispatchPatched, uuidConsumed, origin>>

FetchWrongNetwork ==
  /\ state = "ReferencedRemote"
  /\ ~payloadFetched
  /\ payloadFetched' = TRUE
  /\ digestVerified' = TRUE
  /\ networkBound' = FALSE
  /\ state' = "FetchedVerified"
  /\ UNCHANGED <<reviewShown, userApproved, revalidated, signed, rejected,
                 expired, replayAttempt, broadcasted, signedPatchSent,
                 submitRequested, dispatchPatched, uuidConsumed, origin>>

Review ==
  /\ state = "FetchedVerified"
  /\ payloadFetched
  /\ digestVerified
  /\ networkBound
  /\ ~expired
  /\ reviewShown' = TRUE
  /\ state' = "ReviewDisplayed"
  /\ UNCHANGED <<payloadFetched, digestVerified, userApproved, revalidated,
                 signed, rejected, expired, replayAttempt, networkBound,
                 broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

Approve ==
  /\ state = "ReviewDisplayed"
  /\ reviewShown
  /\ ~rejected
  /\ ~expired
  /\ userApproved' = TRUE
  /\ state' = "Approved"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, revalidated,
                 signed, rejected, expired, replayAttempt, networkBound,
                 broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

Revalidate ==
  /\ state = "Approved"
  /\ userApproved
  /\ ~uuidConsumed
  /\ ~expired
  /\ revalidated' = TRUE
  /\ state' = "Revalidated"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 signed, rejected, expired, replayAttempt, networkBound,
                 broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

Sign ==
  /\ state = "Revalidated"
  /\ revalidated
  /\ networkBound
  /\ ~expired
  /\ ~replayAttempt
  /\ ~uuidConsumed
  /\ signed' = TRUE
  /\ uuidConsumed' = TRUE
  /\ state' = "Signed"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, rejected, expired, replayAttempt, networkBound,
                 broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, origin>>

Reject ==
  /\ state \in {"FetchedVerified", "ReviewDisplayed", "Approved"}
  /\ ~signed
  /\ rejected' = TRUE
  /\ state' = "Rejected"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, expired, replayAttempt, networkBound,
                 broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

Expire ==
  /\ state \in {"ReferencedRemote", "FetchedVerified", "ReviewDisplayed", "Approved"}
  /\ ~signed
  /\ expired' = TRUE
  /\ state' = "Expired"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, replayAttempt, networkBound,
                 broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

ReplayAttempt ==
  /\ uuidConsumed
  /\ state \in {"Signed", "PatchedSigned", "ResultDisplayed"}
  /\ replayAttempt' = TRUE
  /\ state' = "ReplayBlocked"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, expired, networkBound,
                 broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

NetworkMismatchBlock ==
  /\ state = "FetchedVerified"
  /\ payloadFetched
  /\ digestVerified
  /\ ~networkBound
  /\ state' = "NetworkMismatchBlocked"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, expired, replayAttempt,
                 networkBound, broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

PatchSigned ==
  /\ state = "Signed"
  /\ signed
  /\ ~signedPatchSent
  /\ signedPatchSent' = TRUE
  /\ submitRequested' = TRUE
  /\ state' = "PatchedSigned"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, expired, replayAttempt,
                 networkBound, broadcasted, dispatchPatched, uuidConsumed,
                 origin>>

PatchSignedNoSubmit ==
  /\ state = "Signed"
  /\ signed
  /\ ~signedPatchSent
  /\ signedPatchSent' = TRUE
  /\ submitRequested' = FALSE
  /\ state' = "ResultDisplayed"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, expired, replayAttempt,
                 networkBound, broadcasted, dispatchPatched, uuidConsumed,
                 origin>>

Broadcast ==
  /\ state = "PatchedSigned"
  /\ signed
  /\ signedPatchSent
  /\ submitRequested
  /\ ~broadcasted
  /\ broadcasted' = TRUE
  /\ state' = "Submitted"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, expired, replayAttempt,
                 networkBound, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

DispatchPatch ==
  /\ state = "Submitted"
  /\ broadcasted
  /\ ~dispatchPatched
  /\ dispatchPatched' = TRUE
  /\ state' = "DispatchPatched"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, expired, replayAttempt,
                 networkBound, broadcasted, signedPatchSent, submitRequested,
                 uuidConsumed, origin>>

ResultDisplay ==
  /\ state = "DispatchPatched"
  /\ dispatchPatched
  /\ state' = "ResultDisplayed"
  /\ UNCHANGED <<payloadFetched, digestVerified, reviewShown, userApproved,
                 revalidated, signed, rejected, expired, replayAttempt,
                 networkBound, broadcasted, signedPatchSent, submitRequested,
                 dispatchPatched, uuidConsumed, origin>>

Next ==
  \/ Fetch
  \/ FetchWrongNetwork
  \/ Review
  \/ Approve
  \/ Revalidate
  \/ Sign
  \/ Reject
  \/ Expire
  \/ ReplayAttempt
  \/ NetworkMismatchBlock
  \/ PatchSigned
  \/ PatchSignedNoSubmit
  \/ Broadcast
  \/ DispatchPatch
  \/ ResultDisplay

Spec == Init /\ [][Next]_Vars

TypeOK ==
  /\ state \in States
  /\ origin \in Origins
  /\ payloadFetched \in BOOLEAN
  /\ digestVerified \in BOOLEAN
  /\ reviewShown \in BOOLEAN
  /\ userApproved \in BOOLEAN
  /\ revalidated \in BOOLEAN
  /\ signed \in BOOLEAN
  /\ rejected \in BOOLEAN
  /\ expired \in BOOLEAN
  /\ replayAttempt \in BOOLEAN
  /\ networkBound \in BOOLEAN
  /\ broadcasted \in BOOLEAN
  /\ signedPatchSent \in BOOLEAN
  /\ submitRequested \in BOOLEAN
  /\ dispatchPatched \in BOOLEAN
  /\ uuidConsumed \in BOOLEAN

FetchSafety == [](state = "FetchedVerified" => payloadFetched /\ digestVerified)

ReviewRequiresVerifiedFetch ==
  [](reviewShown => payloadFetched /\ digestVerified /\ networkBound)

ApprovalRequiresReview ==
  [](userApproved => reviewShown /\ ~rejected)

RevalidationPrecedesSigning ==
  [](signed => revalidated /\ userApproved)

SigningRequiresFreshNetworkBoundPayload ==
  [](signed => networkBound /\ uuidConsumed /\ ~expired)

RejectionIsTerminalAndUnsigned ==
  [](rejected => state = "Rejected" /\ ~signed /\ ~broadcasted)

ExpirationBlocksSigningAndBroadcast ==
  [](expired => state = "Expired" /\ ~signed /\ ~broadcasted)

ReplayIsBlocked ==
  [](replayAttempt => state = "ReplayBlocked")

NetworkBindingSafety ==
  []((reviewShown \/ signed \/ broadcasted) => networkBound)

BroadcastAfterSignedPatch ==
  [](broadcasted => signed /\ signedPatchSent /\ submitRequested)

THEOREM Spec => []TypeOK
THEOREM Spec => FetchSafety
THEOREM Spec => ReviewRequiresVerifiedFetch
THEOREM Spec => ApprovalRequiresReview
THEOREM Spec => RevalidationPrecedesSigning
THEOREM Spec => SigningRequiresFreshNetworkBoundPayload
THEOREM Spec => RejectionIsTerminalAndUnsigned
THEOREM Spec => ExpirationBlocksSigningAndBroadcast
THEOREM Spec => ReplayIsBlocked
THEOREM Spec => NetworkBindingSafety
THEOREM Spec => BroadcastAfterSignedPatch

===='''


PROPERTY_SPECS: tuple[dict[str, Any], ...] = (
    {
        'id': 'xaman-tla:property:fetch-verifies-payload-before-review',
        'category': 'fetch',
        'operator': 'FetchSafety',
        'transition_actions': ['Fetch', 'FetchWrongNetwork'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:remote-payload-fetch-verifies-request-json-digest',
        ],
        'description': 'Fetched remote payloads must be marked fetched and digest-verified before any review transition can consume them.',
    },
    {
        'id': 'xaman-tla:property:review-requires-verified-network-bound-fetch',
        'category': 'review',
        'operator': 'ReviewRequiresVerifiedFetch',
        'transition_actions': ['Review'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:review-preflight-binds-forced-network-and-signer',
            'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
        ],
        'description': 'The review UI is reachable only after verified fetch and network preflight binding.',
    },
    {
        'id': 'xaman-tla:property:approval-requires-review',
        'category': 'approval',
        'operator': 'ApprovalRequiresReview',
        'transition_actions': ['Approve'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
        ],
        'description': 'Approval cannot precede the displayed transaction review state.',
    },
    {
        'id': 'xaman-tla:property:revalidation-precedes-signing',
        'category': 'revalidation',
        'operator': 'RevalidationPrecedesSigning',
        'transition_actions': ['Revalidate', 'Sign'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
        ],
        'description': 'Remote payload approval must revalidate immediately before the signing boundary.',
    },
    {
        'id': 'xaman-tla:property:signing-requires-fresh-network-bound-payload',
        'category': 'signing',
        'operator': 'SigningRequiresFreshNetworkBoundPayload',
        'transition_actions': ['Sign'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:approval-enters-vault-signing-boundary',
            'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
        ],
        'description': 'Signing requires revalidated, unexpired, network-bound payload state and consumes the payload UUID locally.',
    },
    {
        'id': 'xaman-tla:property:rejection-is-terminal-and-unsigned',
        'category': 'rejection',
        'operator': 'RejectionIsTerminalAndUnsigned',
        'transition_actions': ['Reject'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:rejection-patches-backend-for-user-or-app-decline',
        ],
        'description': 'Rejected payloads terminate without a signature or ledger broadcast.',
    },
    {
        'id': 'xaman-tla:property:expiration-blocks-signing-and-broadcast',
        'category': 'expiration',
        'operator': 'ExpirationBlocksSigningAndBroadcast',
        'transition_actions': ['Expire'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads',
        ],
        'description': 'Expired or already-resolved payloads terminate before signing and broadcast.',
    },
    {
        'id': 'xaman-tla:property:replay-attempt-is-blocked',
        'category': 'replay',
        'operator': 'ReplayIsBlocked',
        'transition_actions': ['ReplayAttempt'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:ledger-submit-has-local-single-submit-and-abort-guards',
        ],
        'description': 'A consumed UUID can only move to the replay-blocked state, not to a second signing path.',
    },
    {
        'id': 'xaman-tla:property:network-binding-before-review-sign-and-broadcast',
        'category': 'network_binding',
        'operator': 'NetworkBindingSafety',
        'transition_actions': ['NetworkMismatchBlock', 'Review', 'Sign', 'Broadcast'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:review-preflight-binds-forced-network-and-signer',
            'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
        ],
        'description': 'Review, signing, and broadcast cannot occur on a payload whose forced network mismatches the active app network.',
    },
    {
        'id': 'xaman-tla:property:broadcast-after-signed-patch',
        'category': 'broadcast',
        'operator': 'BroadcastAfterSignedPatch',
        'transition_actions': ['PatchSigned', 'PatchSignedNoSubmit', 'Broadcast', 'DispatchPatch'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:signed-payload-is-patched-before-optional-ledger-broadcast',
            'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign',
            'xaman-payload-lifecycle:fact:dispatch-result-is-patched-after-ledger-submit',
        ],
        'description': 'Ledger broadcast is reachable only after the signed payload patch and submit-request branch.',
    },
)


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != 'artifact_cid'}


def _claim_ids_by_category(model_payload: dict[str, Any]) -> dict[str, list[str]]:
    categories = {
        'fetch': ['payload_integrity'],
        'review': ['payload_integrity', 'network_binding'],
        'approval': ['payload_integrity'],
        'revalidation': ['payload_integrity', 'replay_prevention'],
        'signing': ['authentication', 'payload_integrity', 'network_binding'],
        'rejection': ['backend_trust'],
        'expiration': ['replay_prevention'],
        'replay': ['replay_prevention', 'backend_trust'],
        'network_binding': ['network_binding'],
        'broadcast': ['transaction_semantics', 'backend_trust'],
    }
    claims = model_payload.get('claims', [])
    return {
        category: sorted(
            claim['id']
            for claim in claims
            if claim.get('xaman_category') in claim_categories
        )
        for category, claim_categories in categories.items()
    }


def _assumption_ids_by_category(model_payload: dict[str, Any]) -> dict[str, list[str]]:
    categories = {
        'fetch': ['payload_integrity'],
        'review': ['payload_integrity', 'network_binding'],
        'approval': ['payload_integrity'],
        'revalidation': ['payload_integrity', 'replay_prevention'],
        'signing': ['authentication', 'payload_integrity', 'network_binding', 'custody'],
        'rejection': ['backend_trust'],
        'expiration': ['replay_prevention'],
        'replay': ['replay_prevention', 'backend_trust'],
        'network_binding': ['network_binding'],
        'broadcast': ['transaction_semantics', 'backend_trust'],
    }
    assumptions = model_payload.get('assumptions', [])
    return {
        category: sorted(
            assumption['id']
            for assumption in assumptions
            if assumption.get('xaman_category') in assumption_categories
        )
        for category, assumption_categories in categories.items()
    }


def _fact_index(lifecycle_facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        fact['id']: fact
        for fact in lifecycle_facts.get('modeled_facts', [])
    }


def build_xaman_tla_workflow_report(
    *,
    model_payload: dict[str, Any],
    model_cid: str,
    lifecycle_facts: dict[str, Any],
    tla_source: str = XAMAN_SIGNING_TLA,
    apalache_executable: str | None = None,
    apalache_version: str | None = None,
) -> dict[str, Any]:
    """Build the deterministic Xaman TLA/Apalache workflow report."""

    fact_index = _fact_index(lifecycle_facts)
    missing_evidence = sorted(
        {
            fact_id
            for property_spec in PROPERTY_SPECS
            for fact_id in property_spec['evidence_fact_ids']
            if fact_id not in fact_index
        }
    )
    solver_available = apalache_executable is not None
    solver_status = 'READY' if solver_available else 'BLOCKED'
    solver_blocker = None if solver_available else {
        'kind': 'missing_solver',
        'solver': 'apalache',
        'message': 'Apalache executable was not available when this workflow report was generated; temporal checks are solver-blocked and must not be accepted as proved.',
        'required_action': 'Install Apalache and rerun the XamanSigning.tla checks before promoting any property to PROVED.',
    }
    claim_ids = _claim_ids_by_category(model_payload)
    assumption_ids = _assumption_ids_by_category(model_payload)

    property_results = []
    for property_spec in PROPERTY_SPECS:
        category = property_spec['category']
        property_results.append(
            {
                **property_spec,
                'claim_ids': claim_ids[category],
                'assumption_ids': assumption_ids[category],
                'modeled': True,
                'classification': 'BLOCKED' if not solver_available else 'READY_TO_CHECK',
                'solver_status': solver_status,
                'solver_blocker': solver_blocker,
                'apalache_command': [
                    'apalache-mc',
                    'check',
                    f'--init={MODULE_NAME}.Init',
                    f'--next={MODULE_NAME}.Next',
                    f'--inv={MODULE_NAME}.TypeOK',
                    f'--inv={MODULE_NAME}.{property_spec["operator"]}',
                    Path(TLA_ARTIFACT_PATH).name,
                ],
            }
        )

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'model_id': model_payload['model_id'],
        'model_cid': model_cid,
        'corpus': {
            'name': lifecycle_facts['corpus'],
            'repo_url': lifecycle_facts['source']['repo_url'],
            'commit_sha': lifecycle_facts['source']['commit_sha'],
            'manifest_aggregate_sha256': lifecycle_facts['source']['manifest_aggregate_sha256'],
            'manifest_schema_version': lifecycle_facts['source']['manifest_schema_version'],
        },
        'tla_module': {
            'module_name': MODULE_NAME,
            'path': TLA_ARTIFACT_PATH,
            'artifact_cid': calculate_artifact_cid(
                {
                    'module_name': MODULE_NAME,
                    'source': tla_source,
                }
            ),
            'line_count': len(tla_source.splitlines()),
            'required_operators': list(REQUIRED_OPERATORS),
            'transition_categories': list(REQUIRED_TRANSITION_CATEGORIES),
        },
        'apalache': {
            'solver': 'apalache',
            'available': solver_available,
            'executable': apalache_executable,
            'version': apalache_version,
            'status': solver_status,
            'blocker': solver_blocker,
        },
        'workflow_model': {
            'source_state_machine_id': 'state_machine:xaman_payload_signing',
            'states': lifecycle_facts['lifecycle_model']['states'],
            'terminal_states': lifecycle_facts['lifecycle_model']['terminal_states'],
            'approval_path': lifecycle_facts['lifecycle_model']['approval_path'],
            'non_broadcast_path': lifecycle_facts['lifecycle_model']['non_broadcast_path'],
            'rejection_path': lifecycle_facts['lifecycle_model']['rejection_path'],
            'tla_terminal_states': [
                'Rejected',
                'Expired',
                'ReplayBlocked',
                'NetworkMismatchBlocked',
                'ResultDisplayed',
            ],
        },
        'summary': {
            'property_count': len(property_results),
            'modeled_property_count': sum(1 for item in property_results if item['modeled']),
            'checked_property_count': 0 if not solver_available else len(property_results),
            'blocked_property_count': 0 if solver_available else len(property_results),
            'missing_evidence_count': len(missing_evidence),
            'apalache_available': solver_available,
            'release_ready': False,
        },
        'missing_evidence_fact_ids': missing_evidence,
        'properties': property_results,
    }
    report['artifact_cid'] = calculate_artifact_cid(_without_artifact_cid(report))
    return report
