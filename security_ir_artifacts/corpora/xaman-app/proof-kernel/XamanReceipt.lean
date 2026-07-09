/-!
Xaman proof-consumer receipt invariants.

This file is a small Lean 4 proof-kernel specification for the checked
consumer predicate used by PORTAL-CXTP-073.  It does not model XRPL protocol
semantics; it proves that a consumer acceptance decision logically entails the
receipt/report bindings required by the Xaman release gate and excludes the
non-secure outcomes that must fail closed.
-/

namespace XamanReceipt

inductive Outcome where
  | proved
  | disproved
  | unknown
  | notModeled
  | missingSolver
  deriving DecidableEq, Repr

structure ReceiptBindings where
  modelCID : Prop
  claimID : Prop
  reportCID : Prop
  solverIdentity : Prop
  assumptions : Prop
  reviewedEvidence : Prop
  corpusCommit : Prop
  freshEnvironment : Prop

structure Receipt where
  outcome : Outcome
  bindings : ReceiptBindings
  solverPresent : Prop
  sourceReviewed : Prop
  environmentFresh : Prop

def AllBindings (b : ReceiptBindings) : Prop :=
  b.modelCID
    /\ b.claimID
    /\ b.reportCID
    /\ b.solverIdentity
    /\ b.assumptions
    /\ b.reviewedEvidence
    /\ b.corpusCommit
    /\ b.freshEnvironment

def Accepts (r : Receipt) : Prop :=
  r.outcome = Outcome.proved
    /\ AllBindings r.bindings
    /\ r.solverPresent
    /\ r.sourceReviewed
    /\ r.environmentFresh

theorem acceptedBindsModelCID {r : Receipt} (h : Accepts r) :
    r.bindings.modelCID := by
  rcases h with ⟨_, hbindings, _, _, _⟩
  rcases hbindings with ⟨hmodel, _, _, _, _, _, _, _⟩
  exact hmodel

theorem acceptedBindsClaimID {r : Receipt} (h : Accepts r) :
    r.bindings.claimID := by
  rcases h with ⟨_, hbindings, _, _, _⟩
  rcases hbindings with ⟨_, hclaim, _, _, _, _, _, _⟩
  exact hclaim

theorem acceptedBindsReportCID {r : Receipt} (h : Accepts r) :
    r.bindings.reportCID := by
  rcases h with ⟨_, hbindings, _, _, _⟩
  rcases hbindings with ⟨_, _, hreport, _, _, _, _, _⟩
  exact hreport

theorem acceptedBindsSolverIdentity {r : Receipt} (h : Accepts r) :
    r.bindings.solverIdentity := by
  rcases h with ⟨_, hbindings, _, _, _⟩
  rcases hbindings with ⟨_, _, _, hsolver, _, _, _, _⟩
  exact hsolver

theorem acceptedBindsAssumptions {r : Receipt} (h : Accepts r) :
    r.bindings.assumptions := by
  rcases h with ⟨_, hbindings, _, _, _⟩
  rcases hbindings with ⟨_, _, _, _, hassumptions, _, _, _⟩
  exact hassumptions

theorem acceptedBindsReviewedEvidence {r : Receipt} (h : Accepts r) :
    r.bindings.reviewedEvidence := by
  rcases h with ⟨_, hbindings, _, _, _⟩
  rcases hbindings with ⟨_, _, _, _, _, hevidence, _, _⟩
  exact hevidence

theorem acceptedBindsCorpusCommit {r : Receipt} (h : Accepts r) :
    r.bindings.corpusCommit := by
  rcases h with ⟨_, hbindings, _, _, _⟩
  rcases hbindings with ⟨_, _, _, _, _, _, hcorpus, _⟩
  exact hcorpus

theorem acceptedBindsFreshEnvironment {r : Receipt} (h : Accepts r) :
    r.bindings.freshEnvironment /\ r.environmentFresh := by
  rcases h with ⟨_, hbindings, _, _, hfresh⟩
  rcases hbindings with ⟨_, _, _, _, _, _, _, hboundFresh⟩
  exact ⟨hboundFresh, hfresh⟩

theorem rejectsDisprovedUnknownNotModeled {r : Receipt}
    (hbad :
      r.outcome = Outcome.disproved
        \/ r.outcome = Outcome.unknown
        \/ r.outcome = Outcome.notModeled) :
    Not (Accepts r) := by
  intro haccept
  rcases haccept with ⟨hproved, _, _, _, _⟩
  rcases hbad with hdisproved | hrest
  · rw [hdisproved] at hproved
    contradiction
  · rcases hrest with hunknown | hnotModeled
    · rw [hunknown] at hproved
      contradiction
    · rw [hnotModeled] at hproved
      contradiction

theorem rejectsMissingSolver {r : Receipt}
    (hmissing : r.outcome = Outcome.missingSolver \/ Not r.solverPresent) :
    Not (Accepts r) := by
  intro haccept
  rcases haccept with ⟨hproved, _, hsolver, _, _⟩
  rcases hmissing with hmissingOutcome | hsolverAbsent
  · rw [hmissingOutcome] at hproved
    contradiction
  · exact hsolverAbsent hsolver

end XamanReceipt
