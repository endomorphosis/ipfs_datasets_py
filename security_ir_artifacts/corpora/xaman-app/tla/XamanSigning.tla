---- MODULE XamanSigning ----
EXTENDS Naturals, Sequences, TLC

\* Xaman signing workflow projection for PORTAL-CXTP-071.
\* This model is intentionally small: it captures the proof obligations that
\* a signature or broadcast cannot occur unless review, digest, auth, vault,
\* and network-binding gates have all succeeded.

VARIABLES
  phase,
  digestChecked,
  authPassed,
  vaultOpened,
  networkBound,
  signed,
  broadcasted,
  rejected

vars == << phase, digestChecked, authPassed, vaultOpened, networkBound, signed, broadcasted, rejected >>

Init ==
  /\ phase = "received"
  /\ digestChecked = FALSE
  /\ authPassed = FALSE
  /\ vaultOpened = FALSE
  /\ networkBound = FALSE
  /\ signed = FALSE
  /\ broadcasted = FALSE
  /\ rejected = FALSE

Review ==
  /\ phase = "received"
  /\ phase' = "reviewed"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, signed, broadcasted, rejected >>

CheckDigest ==
  /\ phase = "reviewed"
  /\ digestChecked' = TRUE
  /\ UNCHANGED << phase, authPassed, vaultOpened, networkBound, signed, broadcasted, rejected >>

Authenticate ==
  /\ phase = "reviewed"
  /\ authPassed' = TRUE
  /\ UNCHANGED << phase, digestChecked, vaultOpened, networkBound, signed, broadcasted, rejected >>

OpenVault ==
  /\ phase = "reviewed"
  /\ authPassed
  /\ vaultOpened' = TRUE
  /\ UNCHANGED << phase, digestChecked, authPassed, networkBound, signed, broadcasted, rejected >>

BindNetwork ==
  /\ phase = "reviewed"
  /\ networkBound' = TRUE
  /\ UNCHANGED << phase, digestChecked, authPassed, vaultOpened, signed, broadcasted, rejected >>

Sign ==
  /\ phase = "reviewed"
  /\ digestChecked
  /\ authPassed
  /\ vaultOpened
  /\ networkBound
  /\ signed' = TRUE
  /\ phase' = "signed"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, broadcasted, rejected >>

Broadcast ==
  /\ phase = "signed"
  /\ signed
  /\ broadcasted' = TRUE
  /\ phase' = "broadcasted"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, signed, rejected >>

Reject ==
  /\ phase \in { "received", "reviewed" }
  /\ rejected' = TRUE
  /\ phase' = "rejected"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, signed, broadcasted >>

Next ==
  \/ Review
  \/ CheckDigest
  \/ Authenticate
  \/ OpenVault
  \/ BindNetwork
  \/ Sign
  \/ Broadcast
  \/ Reject

Spec == Init /\ [][Next]_vars

NoSignWithoutDigest == signed => digestChecked
NoSignWithoutAuthentication == signed => authPassed
NoSignWithoutVault == signed => vaultOpened
NoSignWithoutNetworkBinding == signed => networkBound
NoBroadcastWithoutSignature == broadcasted => signed
NoBroadcastAfterReject == rejected => ~broadcasted

SigningGateInvariant ==
  /\ NoSignWithoutDigest
  /\ NoSignWithoutAuthentication
  /\ NoSignWithoutVault
  /\ NoSignWithoutNetworkBinding
  /\ NoBroadcastWithoutSignature
  /\ NoBroadcastAfterReject

====
