---- MODULE XamanTestnetPayload ----
EXTENDS Naturals

\* PORTAL-CXTP-134: finite Testnet model for payload-resolution concurrency.
\* Two reviewed Testnet clients race to resolve one payload.  The model covers
\* categorical client-visible ordering, terminal resolution stability, duplicate
\* resolution blocking, and the explicit gap where backend atomic single-use is
\* still an unresolved threat-model assumption.

VARIABLES
  \* @type: Str;
  status,
  \* @type: Str;
  lockOwner,
  \* @type: Str;
  resolvedBy,
  \* @type: Str;
  resolutionKind,
  \* @type: Int;
  submitCount,
  \* @type: Str -> Str;
  clientPhase,
  \* @type: Bool;
  testnetBound,
  \* @type: Bool;
  redactionPreserved

Clients == {"clientA", "clientB"}
NoClient == "none"

Statuses ==
  {"Open", "Reviewed", "Signed", "Declined", "Expired", "Cancelled",
   "DuplicateBlocked", "ReplayBlocked"}

TerminalStatuses ==
  {"Signed", "Declined", "Expired", "Cancelled", "DuplicateBlocked",
   "ReplayBlocked"}

ResolutionKinds == {"None", "Signed", "Declined", "Expired", "Cancelled"}
ClientPhases == {"Idle", "Fetched", "Reviewing", "Approved", "Signing",
                 "Submitted", "Refused", "Blocked"}

Vars ==
  << status, lockOwner, resolvedBy, resolutionKind, submitCount, clientPhase,
     testnetBound, redactionPreserved >>

Init ==
  /\ status = "Open"
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ resolutionKind = "None"
  /\ submitCount = 0
  /\ clientPhase = [c \in Clients |-> "Idle"]
  /\ testnetBound = TRUE
  /\ redactionPreserved = TRUE

Fetch(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Idle"
  /\ status \notin TerminalStatuses
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Fetched"]
  /\ UNCHANGED <<status, lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

Review(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Fetched"
  /\ status \in {"Open", "Reviewed"}
  /\ testnetBound
  /\ redactionPreserved
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Reviewing"]
  /\ status' = "Reviewed"
  /\ UNCHANGED <<lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

Approve(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Reviewing"
  /\ status = "Reviewed"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Approved"]
  /\ UNCHANGED <<status, lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

AcquireResolutionLock(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Approved"
  /\ status = "Reviewed"
  /\ lockOwner = NoClient
  /\ lockOwner' = c
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Signing"]
  /\ UNCHANGED <<status, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

SignResolve(c) ==
  /\ c \in Clients
  /\ lockOwner = c
  /\ clientPhase[c] = "Signing"
  /\ status = "Reviewed"
  /\ resolvedBy = NoClient
  /\ submitCount = 0
  /\ status' = "Signed"
  /\ resolvedBy' = c
  /\ resolutionKind' = "Signed"
  /\ submitCount' = 1
  /\ lockOwner' = NoClient
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Submitted"]
  /\ UNCHANGED <<testnetBound, redactionPreserved>>

DeclineResolve(c) ==
  /\ c \in Clients
  /\ clientPhase[c] \in {"Fetched", "Reviewing"}
  /\ status \in {"Open", "Reviewed"}
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ status' = "Declined"
  /\ resolvedBy' = c
  /\ resolutionKind' = "Declined"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Refused"]
  /\ UNCHANGED <<lockOwner, submitCount, testnetBound, redactionPreserved>>

ExpireResolve ==
  /\ status \in {"Open", "Reviewed"}
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ status' = "Expired"
  /\ resolutionKind' = "Expired"
  /\ UNCHANGED <<lockOwner, resolvedBy, submitCount, clientPhase, testnetBound,
                 redactionPreserved>>

CancelResolve ==
  /\ status \in {"Open", "Reviewed"}
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ status' = "Cancelled"
  /\ resolutionKind' = "Cancelled"
  /\ UNCHANGED <<lockOwner, resolvedBy, submitCount, clientPhase, testnetBound,
                 redactionPreserved>>

DuplicateResolveBlocked(c) ==
  /\ c \in Clients
  /\ status \in {"Signed", "Declined", "Expired", "Cancelled"}
  /\ clientPhase[c] \in {"Fetched", "Reviewing", "Approved", "Signing"}
  /\ c # resolvedBy
  /\ status' = "DuplicateBlocked"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Blocked"]
  /\ UNCHANGED <<lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

ReplayBlocked(c) ==
  /\ c \in Clients
  /\ status = "Signed"
  /\ submitCount = 1
  /\ clientPhase[c] \in {"Submitted", "Approved", "Signing"}
  /\ status' = "ReplayBlocked"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Blocked"]
  /\ UNCHANGED <<lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

Next ==
  \/ \E c \in Clients: Fetch(c)
  \/ \E c \in Clients: Review(c)
  \/ \E c \in Clients: Approve(c)
  \/ \E c \in Clients: AcquireResolutionLock(c)
  \/ \E c \in Clients: SignResolve(c)
  \/ \E c \in Clients: DeclineResolve(c)
  \/ ExpireResolve
  \/ CancelResolve
  \/ \E c \in Clients: DuplicateResolveBlocked(c)
  \/ \E c \in Clients: ReplayBlocked(c)

Spec == Init /\ [][Next]_Vars

TypeOK ==
  /\ status \in Statuses
  /\ lockOwner \in Clients \cup {NoClient}
  /\ resolvedBy \in Clients \cup {NoClient}
  /\ resolutionKind \in ResolutionKinds
  /\ submitCount \in 0..1
  /\ clientPhase \in [Clients -> ClientPhases]
  /\ testnetBound \in BOOLEAN
  /\ redactionPreserved \in BOOLEAN

AtMostOneSubmittedResolution ==
  submitCount <= 1

ResolvedPayloadIsTerminal ==
  (resolvedBy # NoClient) => status \in TerminalStatuses

TerminalStateHasResolutionKind ==
  (status \in {"Signed", "Declined", "Expired", "Cancelled"}) =>
    resolutionKind # "None"

NoReviewWithoutTestnetBinding ==
  \A c \in Clients:
    clientPhase[c] \in {"Reviewing", "Approved", "Signing", "Submitted"} =>
      testnetBound

ResolutionRequiresPriorReview ==
  (resolutionKind \in {"Signed", "Declined"}) =>
    \E c \in Clients:
      /\ c = resolvedBy
      /\ clientPhase[c] \in {"Submitted", "Refused", "Blocked"}

DuplicateClientCannotResolveAfterTerminal ==
  status \in {"DuplicateBlocked", "ReplayBlocked"} => submitCount <= 1

THEOREM Spec => []TypeOK
THEOREM Spec => []AtMostOneSubmittedResolution
THEOREM Spec => []ResolvedPayloadIsTerminal
THEOREM Spec => []TerminalStateHasResolutionKind
THEOREM Spec => []NoReviewWithoutTestnetBinding
THEOREM Spec => []ResolutionRequiresPriorReview
THEOREM Spec => []DuplicateClientCannotResolveAfterTerminal

====
