"""Tamarin/ProVerif protocol projection for the Xaman payload flow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


SCHEMA_VERSION = 'xaman-protocol-projection-report/v1'
TASK_ID = 'PORTAL-CXTP-072'
THEORY_NAME = 'XamanPayloadProtocol'
TAMARIN_ARTIFACT_PATH = (
    'security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy'
)
PROTOCOL_REPORT_PATH = (
    'security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json'
)

REQUIRED_ACTION_FACTS = (
    'PayloadSessionCreated',
    'RequesterBound',
    'IntakeAccepted',
    'BackendTrustBoundary',
    'DigestVerified',
    'ReviewDisplayed',
    'ApprovalRecorded',
    'PayloadRevalidated',
    'VaultSecretStored',
    'AuthenticatedVaultOpen',
    'PayloadSigned',
    'SignedPayloadPatched',
    'LedgerBroadcastRequested',
    'ReplayBlocked',
    'PayloadRejected',
    'PayloadExpired',
)

REQUIRED_RULES = (
    'CreatePayloadSession',
    'RegisterSoftwareSignerSecret',
    'TrustedBackendRegistersPayload',
    'QRReferenceIntake',
    'DeepLinkReferenceIntake',
    'PushReferenceIntake',
    'EventListReferenceIntake',
    'FetchAndVerifyRemotePayload',
    'DisplayReview',
    'ApprovePayload',
    'RevalidateBeforeSigning',
    'OpenVaultAfterAuthentication',
    'SignRevalidatedPayload',
    'PatchSignedPayloadToBackend',
    'SubmitPatchedPayloadToLedger',
    'BlockReplayOfConsumedPayload',
    'RejectPayload',
    'ExpirePayload',
)

LEGACY_REQUIRED_LEMMAS = (
    'sign_requires_digest_check',
    'sign_requires_user_approval',
    'sign_requires_auth_and_vault',
    'broadcast_requires_signature',
    'rejected_payload_not_broadcast',
    'nonce_consumed_at_most_once',
)

PROTOCOL_COVERED_CLAIM_IDS = (
    'xaman-claim:payload-integrity-is-digest-checked-and-revalidated',
    'xaman-claim:client-replay-controls-exist-but-backend-single-use-is-blocking',
    'xaman-claim:signing-is-gated-by-auth-and-vault-overlay',
    'xaman-claim:backend-payload-service-is-trusted-not-proved',
)

REQUIRED_LEMMAS = (
    'review_requires_verified_payload',
    'requester_binding_precedes_review',
    'qr_and_deep_link_intake_preserve_requester',
    'signing_requires_auth_revalidation_and_network',
    'modeled_vault_secret_not_revealed',
    'signed_patch_requires_backend_trust',
    'broadcast_requires_signed_patch',
    'local_replay_after_signing_is_blocked',
)

PROTOCOL_CATEGORIES = (
    'session_identity',
    'requester_binding',
    'intake',
    'payload_integrity',
    'replay',
    'secrets',
    'signatures',
    'backend_trust_boundary',
    'broadcast_boundary',
)

XAMAN_PAYLOAD_PROTOCOL_SPTHY = r'''theory XamanPayloadProtocol
begin

builtins: hashing, signing

functions:
  request_json/4,
  payload_ref/2,
  qr_ref/2,
  deep_link_ref/2,
  push_ref/2,
  event_ref/2,
  signed_payload/4,
  backend_patch/3

/*
  PORTAL-CXTP-072: symbolic protocol projection for the Xaman remote payload
  flow. The theory models source-backed client transitions only. Backend
  authorization, native parser/link delivery, native vault cryptography,
  third-party signing correctness, and deployed-runtime equivalence are
  explicit assumptions in protocol-report.json.

  Compatibility aliases:
    Event names: PayloadIssued, PayloadReceived, DigestChecked, UserReviewed,
    UserApproved, AuthPassed, VaultOpened, PayloadBroadcast, PayloadRejected,
    NonceConsumed
    Lemmas: sign_requires_digest_check, sign_requires_user_approval,
    sign_requires_auth_and_vault, broadcast_requires_signature,
    rejected_payload_not_broadcast, nonce_consumed_at_most_once
*/

rule CreatePayloadSession:
  [ Fr(~Sid), Fr(~Uuid) ]
--[
    PayloadSessionCreated(~Sid, ~Uuid, 'requester_app', 'xaman_user', 'xrpl_mainnet'),
    PayloadIssued(~Sid, ~Uuid, 'requester_app', 'xaman_user', 'xrpl_mainnet'),
    RequesterBound(~Sid, ~Uuid, 'requester_app')
  ]->
  [
    !PayloadSession(~Sid, ~Uuid, 'requester_app', 'xaman_user', 'xrpl_mainnet'),
    Out(payload_ref(~Uuid, 'requester_app'))
  ]

rule RegisterSoftwareSignerSecret:
  [ Fr(~Sk) ]
--[
    VaultSecretStored('xaman_user', ~Sk)
  ]->
  [
    !VaultSecret('xaman_user', ~Sk),
    Out(pk(~Sk))
  ]

rule TrustedBackendRegistersPayload:
  [
    !PayloadSession(Sid, Uuid, Requester, Signer, Network)
  ]
--[
    BackendTrustBoundary(Sid, Uuid, Requester, 'payload_registered'),
    PayloadReceived(Sid, Uuid, Requester, Signer, Network),
    RequesterBound(Sid, Uuid, Requester)
  ]->
  [
    !BackendPayloadAuthorized(
      Uuid,
      Requester,
      Signer,
      Network,
      h(request_json(Uuid, Requester, Signer, Network))
    ),
    Out(qr_ref(Uuid, Requester)),
    Out(deep_link_ref(Uuid, Requester)),
    Out(push_ref(Uuid, Requester)),
    Out(event_ref(Uuid, Requester))
  ]

rule QRReferenceIntake:
  [
    !PayloadSession(Sid, Uuid, Requester, Signer, Network),
    In(qr_ref(Uuid, Requester))
  ]
--[
    IntakeAccepted(Sid, Uuid, Requester, 'QR'),
    RequesterBound(Sid, Uuid, Requester)
  ]->
  [
    IntakeState(Sid, Uuid, Requester, Signer, Network, 'QR')
  ]

rule DeepLinkReferenceIntake:
  [
    !PayloadSession(Sid, Uuid, Requester, Signer, Network),
    In(deep_link_ref(Uuid, Requester))
  ]
--[
    IntakeAccepted(Sid, Uuid, Requester, 'DEEP_LINK'),
    RequesterBound(Sid, Uuid, Requester)
  ]->
  [
    IntakeState(Sid, Uuid, Requester, Signer, Network, 'DEEP_LINK')
  ]

rule PushReferenceIntake:
  [
    !PayloadSession(Sid, Uuid, Requester, Signer, Network),
    In(push_ref(Uuid, Requester))
  ]
--[
    IntakeAccepted(Sid, Uuid, Requester, 'PUSH_NOTIFICATION'),
    RequesterBound(Sid, Uuid, Requester)
  ]->
  [
    IntakeState(Sid, Uuid, Requester, Signer, Network, 'PUSH_NOTIFICATION')
  ]

rule EventListReferenceIntake:
  [
    !PayloadSession(Sid, Uuid, Requester, Signer, Network),
    In(event_ref(Uuid, Requester))
  ]
--[
    IntakeAccepted(Sid, Uuid, Requester, 'EVENT_LIST'),
    RequesterBound(Sid, Uuid, Requester)
  ]->
  [
    IntakeState(Sid, Uuid, Requester, Signer, Network, 'EVENT_LIST')
  ]

rule FetchAndVerifyRemotePayload:
  [
    IntakeState(Sid, Uuid, Requester, Signer, Network, Origin),
    !BackendPayloadAuthorized(Uuid, Requester, Signer, Network, Digest)
  ]
--[
    BackendTrustBoundary(Sid, Uuid, Requester, 'authorized_fetch'),
    DigestVerified(Sid, Uuid, Digest),
    DigestChecked(Sid, Uuid, Digest),
    RequesterBound(Sid, Uuid, Requester)
  ]->
  [
    VerifiedPayload(Sid, Uuid, Requester, Signer, Network, Origin, Digest)
  ]

rule DisplayReview:
  [
    VerifiedPayload(Sid, Uuid, Requester, Signer, Network, Origin, Digest)
  ]
--[
    ReviewDisplayed(Sid, Uuid, Requester, Signer, Network, Origin),
    UserReviewed(Sid, Uuid, Requester, Signer, Network, Origin),
    DigestVerified(Sid, Uuid, Digest),
    RequesterBound(Sid, Uuid, Requester)
  ]->
  [
    ReviewState(Sid, Uuid, Requester, Signer, Network, Origin, Digest)
  ]

rule ApprovePayload:
  [
    ReviewState(Sid, Uuid, Requester, Signer, Network, Origin, Digest)
  ]
--[
    UserApproved(Sid, Uuid, Requester, Signer, Network),
    ApprovalRecorded(Sid, Uuid, Requester, Signer)
  ]->
  [
    ApprovedState(Sid, Uuid, Requester, Signer, Network, Origin, Digest)
  ]

rule RevalidateBeforeSigning:
  [
    ApprovedState(Sid, Uuid, Requester, Signer, Network, Origin, Digest),
    !BackendPayloadAuthorized(Uuid, Requester, Signer, Network, Digest)
  ]
--[
    PayloadRevalidated(Sid, Uuid, Requester, Signer, Network),
    DigestVerified(Sid, Uuid, Digest),
    BackendTrustBoundary(Sid, Uuid, Requester, 'pre_sign_revalidation')
  ]->
  [
    RevalidatedState(Sid, Uuid, Requester, Signer, Network, Origin, Digest)
  ]

rule OpenVaultAfterAuthentication:
  [
    RevalidatedState(Sid, Uuid, Requester, Signer, Network, Origin, Digest),
    !VaultSecret(Signer, Sk)
  ]
--[
    AuthenticatedVaultOpen(Sid, Uuid, Signer),
    AuthPassed(Sid, Uuid, Signer),
    VaultOpened(Sid, Uuid, Signer),
    PayloadRevalidated(Sid, Uuid, Requester, Signer, Network)
  ]->
  [
    AuthenticatedState(Sid, Uuid, Requester, Signer, Network, Origin, Digest, Sk)
  ]

rule SignRevalidatedPayload:
  [
    AuthenticatedState(Sid, Uuid, Requester, Signer, Network, Origin, Digest, Sk)
  ]
--[
    PayloadSigned(Sid, Uuid, Requester, Signer, Network),
    AuthenticatedVaultOpen(Sid, Uuid, Signer),
    PayloadRevalidated(Sid, Uuid, Requester, Signer, Network)
  ]->
  [
    SignedState(
      Sid,
      Uuid,
      Requester,
      Signer,
      Network,
      signed_payload(Uuid, Digest, pk(Sk), sign(request_json(Uuid, Requester, Signer, Network), Sk))
    ),
    !ConsumedPayload(Uuid)
  ]

rule PatchSignedPayloadToBackend:
  [
    SignedState(Sid, Uuid, Requester, Signer, Network, SignedPayload),
    !BackendPayloadAuthorized(Uuid, Requester, Signer, Network, Digest)
  ]
--[
    SignedPayloadPatched(Sid, Uuid, Requester, Signer, Network),
    BackendTrustBoundary(Sid, Uuid, Requester, 'signed_patch')
  ]->
  [
    PatchedState(Sid, Uuid, Requester, Signer, Network, backend_patch(Uuid, Requester, SignedPayload))
  ]

rule SubmitPatchedPayloadToLedger:
  [
    PatchedState(Sid, Uuid, Requester, Signer, Network, Patch)
  ]
--[
    LedgerBroadcastRequested(Sid, Uuid, Requester, Signer, Network),
    PayloadBroadcast(Sid, Uuid, Requester, Signer, Network),
    SignedPayloadPatched(Sid, Uuid, Requester, Signer, Network)
  ]->
  [
    SubmittedState(Sid, Uuid, Requester, Signer, Network, Patch)
  ]

rule BlockReplayOfConsumedPayload:
  [
    !PayloadSession(Sid, Uuid, Requester, Signer, Network),
    !ConsumedPayload(Uuid),
    In(payload_ref(Uuid, Requester))
  ]
--[
    ReplayBlocked(Sid, Uuid, Requester),
    NonceConsumed(Sid, Uuid, Requester, Signer)
  ]->
  [
    ReplayBlockedState(Sid, Uuid, Requester, Signer, Network)
  ]

rule RejectPayload:
  [
    ReviewState(Sid, Uuid, Requester, Signer, Network, Origin, Digest)
  ]
--[
    PayloadRejected(Sid, Uuid, Requester),
    BackendTrustBoundary(Sid, Uuid, Requester, 'reject_patch')
  ]->
  [
    RejectedState(Sid, Uuid, Requester, Signer, Network)
  ]

rule ExpirePayload:
  [
    IntakeState(Sid, Uuid, Requester, Signer, Network, Origin)
  ]
--[
    PayloadExpired(Sid, Uuid, Requester)
  ]->
  [
    ExpiredState(Sid, Uuid, Requester, Signer, Network)
  ]

lemma review_requires_verified_payload:
  "All Sid Uuid Requester Signer Network Origin #i.
    ReviewDisplayed(Sid, Uuid, Requester, Signer, Network, Origin) @ i
    ==> (Ex Digest #j. DigestVerified(Sid, Uuid, Digest) @ j & j < i)"

lemma requester_binding_precedes_review:
  "All Sid Uuid Requester Signer Network Origin #i.
    ReviewDisplayed(Sid, Uuid, Requester, Signer, Network, Origin) @ i
    ==> (Ex #j. RequesterBound(Sid, Uuid, Requester) @ j & j < i)"

lemma qr_and_deep_link_intake_preserve_requester:
  "All Sid Uuid Requester Origin #i.
    IntakeAccepted(Sid, Uuid, Requester, Origin) @ i
    & (Origin = 'QR' | Origin = 'DEEP_LINK')
    ==> (Ex #j. RequesterBound(Sid, Uuid, Requester) @ j & (#j < #i | #j = #i))"

lemma signing_requires_auth_revalidation_and_network:
  "All Sid Uuid Requester Signer Network #i.
    PayloadSigned(Sid, Uuid, Requester, Signer, Network) @ i
    ==> (Ex #j #k.
      AuthenticatedVaultOpen(Sid, Uuid, Signer) @ j
      & PayloadRevalidated(Sid, Uuid, Requester, Signer, Network) @ k
      & j < i
      & k < i
      & Network = 'xrpl_mainnet')"

lemma modeled_vault_secret_not_revealed:
  "All Signer Sk #i.
    VaultSecretStored(Signer, Sk) @ i
    ==> not (Ex #j. K(Sk) @ j)"

lemma signed_patch_requires_backend_trust:
  "All Sid Uuid Requester Signer Network #i.
    SignedPayloadPatched(Sid, Uuid, Requester, Signer, Network) @ i
    ==> (Ex #j. BackendTrustBoundary(Sid, Uuid, Requester, 'signed_patch') @ j & (#j < #i | #j = #i))"

lemma broadcast_requires_signed_patch:
  "All Sid Uuid Requester Signer Network #i.
    LedgerBroadcastRequested(Sid, Uuid, Requester, Signer, Network) @ i
    ==> (Ex #j. SignedPayloadPatched(Sid, Uuid, Requester, Signer, Network) @ j & (#j < #i | #j = #i))"

lemma local_replay_after_signing_is_blocked:
  "All Sid Uuid Requester Signer Network #i #j.
    PayloadSigned(Sid, Uuid, Requester, Signer, Network) @ i
    & ReplayBlocked(Sid, Uuid, Requester) @ j
    ==> i < j"

lemma sign_requires_digest_check:
  "All Sid Uuid Requester Signer Network Origin #i.
    ReviewDisplayed(Sid, Uuid, Requester, Signer, Network, Origin) @ i
    ==> (Ex Digest #j. DigestVerified(Sid, Uuid, Digest) @ j & j < i)"

lemma sign_requires_user_approval:
  "All Sid Uuid Requester Signer Network #i.
    PayloadSigned(Sid, Uuid, Requester, Signer, Network) @ i
    ==> (Ex #j. RequesterBound(Sid, Uuid, Requester) @ j & (#j < #i | #j = #i))"

lemma sign_requires_auth_and_vault:
  "All Sid Uuid Requester Signer Network #i.
    PayloadSigned(Sid, Uuid, Requester, Signer, Network) @ i
    ==> (Ex #j #k.
      AuthenticatedVaultOpen(Sid, Uuid, Signer) @ j
      & PayloadRevalidated(Sid, Uuid, Requester, Signer, Network) @ k
      & j < i
      & k < i)"

lemma broadcast_requires_signature:
  "All Sid Uuid Requester Signer Network #i.
    LedgerBroadcastRequested(Sid, Uuid, Requester, Signer, Network) @ i
    ==> (Ex #j. PayloadSigned(Sid, Uuid, Requester, Signer, Network) @ j & (#j < #i | #j = #i))"

lemma rejected_payload_not_broadcast:
  "All Sid Uuid Requester #i.
    PayloadRejected(Sid, Uuid, Requester) @ i
    ==> (All #j. All Signer Network.
          (LedgerBroadcastRequested(Sid, Uuid, Requester, Signer, Network) @ #j) ==> (#j < #i))"

lemma nonce_consumed_at_most_once:
  "All Sid Uuid Requester #i.
    ReplayBlocked(Sid, Uuid, Requester) @ i
    ==> (Ex #j. PayloadSigned(Sid, Uuid, Requester, Signer, Network) @ j & j < i)"

end'''


PROPERTY_SPECS: tuple[dict[str, Any], ...] = (
    {
        'id': 'xaman-protocol:property:session-identity-created-and-carried',
        'category': 'session_identity',
        'lemma': 'requester_binding_precedes_review',
        'rule_names': ['CreatePayloadSession', 'DisplayReview'],
        'action_facts': ['PayloadSessionCreated', 'RequesterBound', 'ReviewDisplayed'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:payload-build-creates-local-sign-request',
            'xaman-payload-lifecycle:fact:payload-types-carry-expiration-origin-and-network-fields',
        ],
        'claim_categories': ['payload_integrity'],
        'assumption_categories': ['payload_integrity'],
        'description': 'Payload UUID and session identity are created once and carried into review events with the requester binding.',
    },
    {
        'id': 'xaman-protocol:property:requester-binding-precedes-review',
        'category': 'requester_binding',
        'lemma': 'requester_binding_precedes_review',
        'rule_names': ['TrustedBackendRegistersPayload', 'FetchAndVerifyRemotePayload', 'DisplayReview'],
        'action_facts': ['RequesterBound', 'BackendTrustBoundary', 'ReviewDisplayed'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:review-preflight-binds-forced-network-and-signer',
            'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
        ],
        'claim_categories': ['payload_integrity', 'network_binding'],
        'assumption_categories': ['payload_integrity', 'network_binding'],
        'description': 'The requester binding is observed before the transaction review UI can display a remote payload.',
    },
    {
        'id': 'xaman-protocol:property:qr-and-deep-link-intake-preserve-requester',
        'category': 'intake',
        'lemma': 'qr_and_deep_link_intake_preserve_requester',
        'rule_names': ['QRReferenceIntake', 'DeepLinkReferenceIntake'],
        'action_facts': ['IntakeAccepted', 'RequesterBound'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:qr-payload-reference-intake-fetches-and-routes-to-review',
            'xaman-payload-lifecycle:fact:deep-link-payload-reference-intake-fetches-and-routes-to-review',
            'xaman-payload-lifecycle:fact:push-notification-payload-intake-fetches-with-push-origin',
            'xaman-payload-lifecycle:fact:event-list-loads-pending-payloads-and-opens-review',
        ],
        'claim_categories': ['payload_integrity'],
        'assumption_categories': ['payload_integrity'],
        'description': 'QR and deep-link intake rules preserve the decoded requester value when routing to payload fetch.',
    },
    {
        'id': 'xaman-protocol:property:digest-verification-precedes-review',
        'category': 'payload_integrity',
        'lemma': 'review_requires_verified_payload',
        'rule_names': ['FetchAndVerifyRemotePayload', 'DisplayReview'],
        'action_facts': ['DigestVerified', 'ReviewDisplayed'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:remote-payload-fetch-verifies-request-json-digest',
            'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
        ],
        'claim_categories': ['payload_integrity'],
        'assumption_categories': ['payload_integrity'],
        'description': 'A review event requires an earlier digest verification event for the same session and UUID.',
    },
    {
        'id': 'xaman-protocol:property:local-replay-after-signing-is-blocked',
        'category': 'replay',
        'lemma': 'local_replay_after_signing_is_blocked',
        'rule_names': ['SignRevalidatedPayload', 'BlockReplayOfConsumedPayload'],
        'action_facts': ['PayloadSigned', 'ReplayBlocked'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads',
            'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
            'xaman-payload-lifecycle:fact:ledger-submit-has-local-single-submit-and-abort-guards',
        ],
        'claim_categories': ['replay_prevention'],
        'assumption_categories': ['replay_prevention'],
        'description': 'The modeled client can only enter replay-blocked state after a consumed payload UUID is replayed.',
    },
    {
        'id': 'xaman-protocol:property:modeled-vault-secret-not-output',
        'category': 'secrets',
        'lemma': 'modeled_vault_secret_not_revealed',
        'rule_names': ['RegisterSoftwareSignerSecret', 'OpenVaultAfterAuthentication', 'SignRevalidatedPayload'],
        'action_facts': ['VaultSecretStored', 'AuthenticatedVaultOpen', 'PayloadSigned'],
        'evidence_fact_ids': [
            'xaman-wallet-auth:fact:vault-access-is-through-native-module',
            'xaman-wallet-auth:fact:software-private-key-signing-requires-vault-open-with-encryption-key',
            'xaman-wallet-auth:fact:account-secret-vaulted-for-full-access',
        ],
        'claim_categories': ['custody'],
        'assumption_categories': ['custody'],
        'description': 'The source-level model never emits the software signing secret; it remains behind the vault facade.',
    },
    {
        'id': 'xaman-protocol:property:signature-requires-auth-and-revalidation',
        'category': 'signatures',
        'lemma': 'signing_requires_auth_revalidation_and_network',
        'rule_names': ['RevalidateBeforeSigning', 'OpenVaultAfterAuthentication', 'SignRevalidatedPayload'],
        'action_facts': ['PayloadRevalidated', 'AuthenticatedVaultOpen', 'PayloadSigned'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
            'xaman-payload-lifecycle:fact:approval-enters-vault-signing-boundary',
            'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
            'xaman-wallet-auth:fact:vault-overlay-selects-signer-and-auth-method-from-access-and-encryption-level',
            'xaman-wallet-auth:fact:transaction-signing-preconditions-before-vault-overlay',
            'xaman-wallet-auth:fact:signed-object-callback-must-include-blob-pubkey-method-and-id-for-non-pseudo',
        ],
        'claim_categories': ['authentication', 'payload_integrity', 'network_binding'],
        'assumption_categories': ['authentication', 'payload_integrity', 'network_binding'],
        'description': 'A signature event requires pre-sign revalidation, authenticated vault opening, and the modeled network binding.',
    },
    {
        'id': 'xaman-protocol:property:signed-patch-stays-at-backend-trust-boundary',
        'category': 'backend_trust_boundary',
        'lemma': 'signed_patch_requires_backend_trust',
        'rule_names': ['TrustedBackendRegistersPayload', 'PatchSignedPayloadToBackend'],
        'action_facts': ['BackendTrustBoundary', 'SignedPayloadPatched'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:signed-payload-is-patched-before-optional-ledger-broadcast',
            'xaman-payload-lifecycle:fact:dispatch-result-is-patched-after-ledger-submit',
        ],
        'claim_categories': ['backend_trust'],
        'assumption_categories': ['backend_trust'],
        'description': 'Signed payload patching is modeled as crossing an explicit backend authorization boundary.',
    },
    {
        'id': 'xaman-protocol:property:broadcast-requires-signed-patch',
        'category': 'broadcast_boundary',
        'lemma': 'broadcast_requires_signed_patch',
        'rule_names': ['PatchSignedPayloadToBackend', 'SubmitPatchedPayloadToLedger'],
        'action_facts': ['SignedPayloadPatched', 'LedgerBroadcastRequested'],
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:signed-payload-is-patched-before-optional-ledger-broadcast',
            'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign',
            'xaman-payload-lifecycle:fact:submit-request-type-boundary-is-xrpl-submit',
            'xaman-wallet-auth:fact:submit-requires-signed-blob-single-submit-and-not-aborted',
        ],
        'claim_categories': ['backend_trust', 'transaction_semantics'],
        'assumption_categories': ['backend_trust', 'transaction_semantics'],
        'description': 'Optional ledger broadcast is reachable only after the signed payload has been patched through the backend boundary.',
    },
)

REJECTED_CLAIM_SPECS: tuple[dict[str, Any], ...] = (
    {
        'id': 'xaman-protocol:rejected:backend-global-single-use-and-authorization',
        'claim_ids': [
            'xaman-security:claim:backend-trust-boundary-is-safe-for-payload-resolution',
            'xaman-security:claim:payload-replay-prevention-is-single-use',
        ],
        'blocked_by_assumption_ids': [
            'xaman-security:assumption:backend-payload-api-single-use-and-authorization',
        ],
        'gap_ids': [
            'xaman-payload-lifecycle:gap:backend-payload-creation-auth-and-single-use',
        ],
        'reason': 'Backend authorization, atomic resolution, cross-device replay prevention, and PATCH conflict behavior are not available in the reviewed client-source evidence.',
    },
    {
        'id': 'xaman-protocol:rejected:native-intake-parser-and-delivery-integrity',
        'claim_ids': [
            'xaman-security:claim:payload-integrity-before-review-and-signing',
        ],
        'blocked_by_assumption_ids': [
            'xaman-security:assumption:intake-decoder-and-os-delivery-integrity',
        ],
        'gap_ids': [
            'xaman-payload-lifecycle:gap:string-decoder-and-native-intake-integrity',
        ],
        'reason': 'QR image parsing, third-party string decoding, native camera behavior, OS deep-link routing, clipboard, and malformed-input behavior are outside the source-backed client model.',
    },
    {
        'id': 'xaman-protocol:rejected:native-vault-cryptographic-secrecy',
        'claim_ids': [
            'xaman-security:claim:custody-software-private-key-not-available-without-authorized-vault-path',
        ],
        'blocked_by_assumption_ids': [
            'xaman-security:assumption:native-vault-cryptographic-confidentiality',
            'xaman-security:assumption:passcode-kdf-and-secret-protection',
            'xaman-security:assumption:biometric-native-binding',
        ],
        'gap_ids': [
            'xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation',
            'xaman-wallet-auth:gap:passcode-hash-kdf-strength',
            'xaman-wallet-auth:gap:biometric-native-security-properties',
        ],
        'reason': 'The protocol projection can show that source-level rules do not output secrets, but not native keychain, KDF, biometric, or memory-handling security.',
    },
    {
        'id': 'xaman-protocol:rejected:third-party-signature-correctness',
        'claim_ids': [
            'xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent',
        ],
        'blocked_by_assumption_ids': [
            'xaman-security:assumption:third-party-signing-correctness',
            'xaman-security:assumption:trustset-and-signerlist-client-validation',
            'xaman-security:assumption:xrpl-server-rule-enforcement-and-consensus',
        ],
        'gap_ids': [
            'xaman-wallet-auth:gap:third-party-signing-library-correctness',
            'xaman-payload-lifecycle:gap:ledger-consensus-and-node-honesty',
        ],
        'reason': 'The model records when signing is invoked and what callback evidence is required, but not cryptographic library, SDK, firmware, or XRPL server-rule correctness.',
    },
    {
        'id': 'xaman-protocol:rejected:deployed-runtime-equivalence',
        'claim_ids': [
            'xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime',
        ],
        'blocked_by_assumption_ids': [
            'xaman-security:assumption:deployed-runtime-equivalence',
            'xaman-security:assumption:deployed-network-and-node-config-equivalence',
        ],
        'gap_ids': [
            'xaman-payload-lifecycle:gap:deployed-runtime-equivalence',
            'xaman-wallet-auth:gap:runtime-and-deployed-binary-behavior',
        ],
        'reason': 'A symbolic protocol theory over pinned source facts cannot prove app-store binary, native runtime, backend deployment, or production configuration equivalence.',
    },
)

NEGATIVE_CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        'id': 'xaman-protocol:negative:reused-uuid-after-consumption',
        'attack_class': 'replay_payload',
        'expected_action_fact': 'ReplayBlocked',
        'blocked_by_property_id': 'xaman-protocol:property:local-replay-after-signing-is-blocked',
        'description': 'A replayed payload reference for a consumed UUID is routed to ReplayBlockedState in the modeled client.',
    },
    {
        'id': 'xaman-protocol:negative:expired-or-resolved-payload',
        'attack_class': 'stale_or_resolved_payload',
        'expected_action_fact': 'PayloadExpired',
        'evidence_fact_ids': [
            'xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads',
        ],
        'description': 'Expired or already-resolved payloads are modeled as terminal before signing.',
    },
    {
        'id': 'xaman-protocol:negative:mismatched-requester-app-source',
        'attack_class': 'requester_substitution',
        'expected_action_fact': 'RequesterBound',
        'blocked_by_property_id': 'xaman-protocol:property:requester-binding-precedes-review',
        'description': 'Review requires the requester value carried by the accepted payload reference and backend authorization fact.',
    },
    {
        'id': 'xaman-protocol:negative:tampered-request-json-digest',
        'attack_class': 'digest_tampering',
        'expected_action_fact': 'DigestVerified',
        'blocked_by_property_id': 'xaman-protocol:property:digest-verification-precedes-review',
        'description': 'Review is unreachable without a matching BackendPayloadAuthorized digest fact.',
    },
    {
        'id': 'xaman-protocol:negative:wrong-network-before-signing',
        'attack_class': 'wrong_network',
        'expected_action_fact': 'PayloadSigned',
        'blocked_by_property_id': 'xaman-protocol:property:signature-requires-auth-and-revalidation',
        'description': 'The signing lemma binds the modeled flow to the network value accepted at session creation and revalidation.',
    },
    {
        'id': 'xaman-protocol:negative:missing-auth-before-signing',
        'attack_class': 'auth_precondition_removed',
        'expected_action_fact': 'AuthenticatedVaultOpen',
        'blocked_by_property_id': 'xaman-protocol:property:signature-requires-auth-and-revalidation',
        'description': 'PayloadSigned requires an earlier AuthenticatedVaultOpen event for the same session and signer.',
    },
    {
        'id': 'xaman-protocol:negative:duplicate-submit-race',
        'attack_class': 'duplicate_submit',
        'expected_action_fact': 'LedgerBroadcastRequested',
        'blocked_by_property_id': 'xaman-protocol:property:broadcast-requires-signed-patch',
        'description': 'The modeled broadcast path is downstream of signed backend patching and local submit guards.',
    },
)


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != 'artifact_cid'}


def _modeled_fact_index(*fact_payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for payload in fact_payloads:
        for fact in payload.get('modeled_facts', []):
            indexed[fact['id']] = fact
    return indexed


def _gap_index(*fact_payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for payload in fact_payloads:
        for gap in payload.get('not_modeled_gaps', []):
            indexed[gap['id']] = gap
    return indexed


def _ids_by_category(
    items: list[Mapping[str, Any]],
    categories: list[str],
) -> list[str]:
    return sorted(
        item['id']
        for item in items
        if item.get('xaman_category') in categories
    )


def _assumption_index(model_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        assumption['id']: assumption
        for assumption in model_payload.get('assumptions', [])
    }


def _resolve_assumption_id(
    assumption_id: str,
    assumption_index: Mapping[str, dict[str, Any]],
) -> str | None:
    if assumption_id in assumption_index:
        return assumption_id

    legacy_candidates = (
        assumption_id.replace(
            'xaman-security:assumption:',
            'xaman-assumption:',
            1,
        ),
        assumption_id.replace(
            'xaman-assumption:',
            'xaman-security:assumption:',
            1,
        ),
    )
    for candidate in legacy_candidates:
        if candidate in assumption_index:
            return candidate

    legacy_name_map = {
        'xaman-security:assumption:backend-payload-api-single-use-and-authorization': (
            'xaman-assumption:backend-payload-api-auth-single-use-and-expiration'
        ),
    }
    mapped = legacy_name_map.get(assumption_id)
    if mapped is not None and mapped in assumption_index:
        return mapped

    return None


def _sha256_fallback_artifact(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _normalize_artifact_cid(payload: Mapping[str, Any]) -> str:
    cid = calculate_artifact_cid(payload)
    if cid.startswith('sha256:'):
        return cid
    return _sha256_fallback_artifact(payload)


def _solver_blocker(solver: str, theory_name: str) -> dict[str, str]:
    return {
        'kind': 'missing_solver',
        'solver': solver,
        'message': f'{solver} executable was not available when this protocol report was generated; symbolic protocol checks are solver-blocked and must not be accepted as proved.',
        'required_action': f'Install {solver} and rerun the {theory_name} protocol checks before promoting any protocol property to PROVED.',
    }


def build_xaman_protocol_report(
    *,
    model_payload: dict[str, Any],
    model_cid: str,
    lifecycle_facts: dict[str, Any],
    wallet_auth_facts: dict[str, Any],
    tamarin_source: str = XAMAN_PAYLOAD_PROTOCOL_SPTHY,
    tamarin_executable: str | None = None,
    tamarin_version: str | None = None,
    proverif_executable: str | None = None,
    proverif_version: str | None = None,
) -> dict[str, Any]:
    """Build the deterministic Xaman protocol projection report."""

    fact_index = _modeled_fact_index(lifecycle_facts, wallet_auth_facts)
    gap_index = _gap_index(lifecycle_facts, wallet_auth_facts)
    assumptions = model_payload.get('assumptions', [])
    claims = model_payload.get('claims', [])
    assumption_index = _assumption_index(model_payload)

    missing_evidence = sorted(
        {
            fact_id
            for property_spec in PROPERTY_SPECS
            for fact_id in property_spec['evidence_fact_ids']
            if fact_id not in fact_index
        }
    )
    missing_gap_records = sorted(
        {
            gap_id
            for rejected in REJECTED_CLAIM_SPECS
            for gap_id in rejected['gap_ids']
            if gap_id not in gap_index
        }
    )

    tamarin_available = tamarin_executable is not None
    proverif_available = proverif_executable is not None
    tamarin_blocker = None if tamarin_available else _solver_blocker(
        'tamarin-prover',
        THEORY_NAME,
    )
    proverif_blocker = None if proverif_available else _solver_blocker(
        'proverif',
        THEORY_NAME,
    )
    blockers = [blocker for blocker in (tamarin_blocker, proverif_blocker) if blocker is not None]
    if not blockers:
        blockers.append(
            {
                'code': 'PROTOCOL_MODEL_NOT_CHECKED',
                'message': (
                    'Projection report generation intentionally omits Tamarin/ProVerif execution; '
                    'run protocol solver checks before treating this as checked.'
                ),
            }
        )
    model_hash = 'sha256:' + hashlib.sha256(tamarin_source.encode('utf-8')).hexdigest()

    properties = []
    for property_spec in PROPERTY_SPECS:
        claim_ids = _ids_by_category(claims, property_spec['claim_categories'])
        assumption_ids = _ids_by_category(
            assumptions,
            property_spec['assumption_categories'],
        )
        unresolved_assumption_ids = []
        blocking_assumptions = sorted(
            assumption_id
            for assumption_id in assumption_ids
            if (
                assumption_index.get(
                    _resolve_assumption_id(
                        assumption_id,
                        assumption_index,
                    )
                )
                or {}
            ).get('acceptance_status')
            == 'BLOCKING'
        )
        for assumption_id in assumption_ids:
            if _resolve_assumption_id(assumption_id, assumption_index) is None:
                unresolved_assumption_ids.append(assumption_id)
        classification = 'READY_TO_CHECK' if tamarin_available else 'BLOCKED'
        properties.append(
            {
                **property_spec,
                'claim_ids': claim_ids,
                'assumption_ids': assumption_ids,
                'blocking_assumption_ids': blocking_assumptions,
                'unresolved_assumption_ids': sorted(set(unresolved_assumption_ids)),
                'modeled': True,
                'classification': classification,
                'solver_status': 'READY' if tamarin_available else 'BLOCKED',
                'solver_blocker': tamarin_blocker,
                'tamarin_command': [
                    'tamarin-prover',
                    '--prove',
                    f'--prove={property_spec["lemma"]}',
                    Path(TAMARIN_ARTIFACT_PATH).name,
                ],
                'proverif_equivalent_query': {
                    'status': 'BLOCKED' if not proverif_available else 'READY_TO_TRANSLATE',
                    'solver_blocker': proverif_blocker,
                    'query': f'equivalent reachability/secrecy query for {property_spec["lemma"]}',
                },
            }
        )

    rejected_claims = []
    for rejected in REJECTED_CLAIM_SPECS:
        required_evidence: list[str] = []
        missing_assumption_ids: list[str] = []
        for assumption_id in rejected['blocked_by_assumption_ids']:
            resolved_id = _resolve_assumption_id(
                assumption_id,
                assumption_index,
            )
            if resolved_id is None:
                missing_assumption_ids.append(assumption_id)
                continue
            required_evidence.extend(
                resolved.get('required_evidence_to_accept', [])
                for resolved in [assumption_index[resolved_id]]
            )
        rejected_claims.append(
            {
                **rejected,
                'classification': 'REJECTED_UNAVAILABLE_EVIDENCE',
                'modeled': False,
                'solver_status': 'NOT_SUBMITTED',
                'required_evidence_to_accept': sorted(
                    evidence
                    for evidence in [
                        item
                        for nested in required_evidence
                        for item in nested
                    ]
                ),
                'missing_assumption_ids': sorted(set(missing_assumption_ids)),
                'gap_summaries': [
                    gap_index[gap_id]['summary']
                    for gap_id in rejected['gap_ids']
                    if gap_id in gap_index
                ],
            }
        )

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'model_id': model_payload['model_id'],
        'model_cid': model_cid,
        'overall_status': 'blocked_optional_lane',
        'security_decision': 'BLOCK_PROTOCOL_SOLVERS_UNAVAILABLE',
        'production_release_blocked_by_protocol_lane': True,
        'covered_claim_ids': list(PROTOCOL_COVERED_CLAIM_IDS),
        'blockers': blockers,
        'model_check': {
            'run_status': 'not-run',
            'reason': (
                'Solver checks are not executed during projection report generation. '
                'Run protocol solver checks to execute Tamarin/ProVerif evidence generation.'
            ),
            'tamarin': {
                'solver': 'tamarin-prover',
                'available': tamarin_available,
                'executable': tamarin_executable,
                'version': tamarin_version,
            },
            'proverif': {
                'solver': 'proverif',
                'available': proverif_available,
                'executable': proverif_executable,
                'version': proverif_version,
            },
        },
        'corpus': {
            'name': lifecycle_facts['corpus'],
            'repo_url': lifecycle_facts['source']['repo_url'],
            'commit_sha': lifecycle_facts['source']['commit_sha'],
            'manifest_aggregate_sha256': lifecycle_facts['source']['manifest_aggregate_sha256'],
            'manifest_schema_version': lifecycle_facts['source']['manifest_schema_version'],
        },
        'protocol_model': {
            'theory_name': THEORY_NAME,
            'path': TAMARIN_ARTIFACT_PATH,
            'sha256': model_hash,
            'artifact_cid': calculate_artifact_cid(
                {
                    'theory_name': THEORY_NAME,
                    'source': tamarin_source,
                }
            ),
            'source_byte_length': len(tamarin_source),
            'line_count': len(tamarin_source.splitlines()),
            'lemmas': list(LEGACY_REQUIRED_LEMMAS),
            'required_rules': list(REQUIRED_RULES),
            'required_action_facts': list(REQUIRED_ACTION_FACTS),
            'required_lemmas': list(REQUIRED_LEMMAS),
            'categories': list(PROTOCOL_CATEGORIES),
            'modeled_intake_origins': [
                'QR',
                'DEEP_LINK',
                'PUSH_NOTIFICATION',
                'EVENT_LIST',
            ],
            'backend_boundary': 'BackendPayloadAuthorized is an explicit trusted precondition; backend authorization and atomicity are rejected when claimed without backend evidence.',
        },
        'solvers': {
            'tamarin': {
                'solver': 'tamarin-prover',
                'available': tamarin_available,
                'executable': tamarin_executable,
                'version': tamarin_version,
                'status': 'READY' if tamarin_available else 'BLOCKED',
                'blocker': tamarin_blocker,
            },
            'proverif': {
                'solver': 'proverif',
                'available': proverif_available,
                'executable': proverif_executable,
                'version': proverif_version,
                'status': 'READY' if proverif_available else 'BLOCKED',
                'blocker': proverif_blocker,
            },
        },
        'evidence_scope': {
            'source_backed_claims': (
                lifecycle_facts['derived_security_boundary']['claimed']
                + wallet_auth_facts['derived_security_boundary']['source_backed_claims']
            ),
            'not_claimed': (
                lifecycle_facts['derived_security_boundary']['not_claimed']
                + wallet_auth_facts['derived_security_boundary']['not_claimed']
            ),
            'missing_evidence_fact_ids': missing_evidence,
            'missing_gap_record_ids': missing_gap_records,
        },
        'summary': {
            'property_count': len(properties),
            'modeled_property_count': sum(1 for item in properties if item['modeled']),
            'checked_property_count': 0 if not tamarin_available else len(properties),
            'blocked_property_count': 0 if tamarin_available else len(properties),
            'rejected_claim_count': len(rejected_claims),
            'negative_case_count': len(NEGATIVE_CASE_SPECS),
            'missing_evidence_count': len(missing_evidence),
            'tamarin_available': tamarin_available,
            'proverif_available': proverif_available,
            'release_ready': False,
        },
        'properties': properties,
        'negative_cases': list(NEGATIVE_CASE_SPECS),
        'rejected_claims': rejected_claims,
    }
    report['artifact_cid'] = _normalize_artifact_cid(_without_artifact_cid(report))
    return report
