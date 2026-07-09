---- MODULE XamanSigning ----
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

====
